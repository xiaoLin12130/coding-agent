"""Browser and login recovery (M6).

The real-page tests use the M1 fixture; the fake-session tests pin the decision
logic (restart budget, one-retry policy, login timeout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.profiles import load_profile
from app.browser.web_chat import WebChatProvider
from app.recovery import BrowserRecovery, default_probe
from tests.conftest import PROFILES_DIR, make_driver


# --- fakes -----------------------------------------------------------------


class FakeProvider:
    def __init__(self, logged_in: bool = True, recover_result: bool = True) -> None:
        self.logged_in = logged_in
        self.recover_result = recover_result
        self.recover_calls: list[int | None] = []

    def is_logged_in(self) -> bool:
        return self.logged_in

    def recover_session(self, timeout_ms: int | None = None) -> bool:
        self.recover_calls.append(timeout_ms)
        self.logged_in = self.recover_result
        return self.recover_result


class FakeDriver:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.closed = False

    def page_url(self) -> str:
        if not self.alive:
            raise RuntimeError("the page is closed")
        return "about:blank"

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, alive: bool = True, logged_in: bool = True, recover_result: bool = True) -> None:
        self.driver = FakeDriver(alive)
        self.provider = FakeProvider(logged_in, recover_result)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.driver.close()


def factory_from(*sessions):
    """A factory that hands out the given sessions in order."""
    queue = list(sessions)

    def factory():
        if not queue:
            raise RuntimeError("no more sessions")
        return queue.pop(0)

    return factory


# --- decision logic --------------------------------------------------------


def test_a_live_logged_in_session_needs_no_recovery() -> None:
    recovery = BrowserRecovery(factory_from(FakeSession()))

    report = recovery.ensure_ready()

    assert report.failed is False
    assert report.outcome == "not_needed"
    assert report.notes() == ["browser session is alive", "login is valid"]


def test_a_dead_session_is_restarted() -> None:
    dead = FakeSession(alive=False)
    fresh = FakeSession()
    recovery = BrowserRecovery(factory_from(dead, fresh))

    report = recovery.ensure_ready()

    assert report.recovered is True
    assert dead.closed is True, "the dead session is closed before the restart"
    assert recovery.restarts == 1
    assert "relaunched the browser" in report.notes()


def test_the_restart_budget_is_enforced() -> None:
    recovery = BrowserRecovery(factory_from(FakeSession(alive=False)), max_restarts=1)

    first = recovery.restart()
    second = recovery.restart()

    assert first.recovered is True
    assert second.failed is True
    assert "budget" in second.message


def test_a_factory_failure_is_reported_not_raised() -> None:
    recovery = BrowserRecovery(factory_from())

    report = recovery.restart()

    assert report.failed is True
    assert "could not relaunch" in report.message


def test_an_expired_login_waits_for_the_human() -> None:
    session = FakeSession(logged_in=False, recover_result=True)
    recovery = BrowserRecovery(factory_from(session), login_timeout_ms=1234)

    report = recovery.ensure_logged_in()

    assert report.recovered is True
    assert session.provider.recover_calls == [1234]
    assert "signed in again" in report.message


def test_a_login_that_is_not_restored_fails_cleanly() -> None:
    session = FakeSession(logged_in=False, recover_result=False)
    recovery = BrowserRecovery(factory_from(session))

    report = recovery.ensure_logged_in(timeout_ms=10)

    assert report.failed is True
    assert "still signed out" in report.message


def test_a_login_check_that_raises_is_reported() -> None:
    session = FakeSession()

    def explode():
        raise RuntimeError("provider is gone")

    session.provider.is_logged_in = explode
    recovery = BrowserRecovery(factory_from(session))

    report = recovery.ensure_logged_in()

    assert report.failed is True
    assert "could not determine" in report.message


def test_a_live_login_needs_no_wait() -> None:
    session = FakeSession(logged_in=True)
    recovery = BrowserRecovery(factory_from(session))

    report = recovery.ensure_logged_in()

    assert report.outcome == "not_needed"
    assert session.provider.recover_calls == []


def test_call_recovers_once_and_succeeds() -> None:
    dead = FakeSession(alive=False)
    fresh = FakeSession()
    recovery = BrowserRecovery(factory_from(dead, fresh))
    attempts = {"n": 0}

    def work(session):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("the page died mid-call")
        return "the answer"

    value, report = recovery.call(work)

    assert value == "the answer"
    assert report.recovered is True or report.outcome == "not_needed"
    assert attempts["n"] == 2


def test_call_retries_once_and_then_reports_failure() -> None:
    recovery = BrowserRecovery(factory_from(FakeSession(), FakeSession()))
    attempts = {"n": 0}

    def always_fails(session):
        attempts["n"] += 1
        raise RuntimeError("still broken")

    value, report = recovery.call(always_fails)

    assert value is None
    assert report.failed is True
    assert attempts["n"] == 2, "exactly one retry, never an endless loop"
    assert "failed again" in report.message


def test_call_reports_the_original_error_when_recovery_fails() -> None:
    recovery = BrowserRecovery(factory_from(FakeSession(alive=False)), max_restarts=0)

    def fails(session):
        raise RuntimeError("page exploded")

    value, report = recovery.call(fails)

    assert value is None
    assert report.failed is True
    assert "page exploded" in report.message


def test_call_without_a_problem_is_transparent() -> None:
    recovery = BrowserRecovery(factory_from(FakeSession()))

    value, report = recovery.call(lambda session: "fine")

    assert value == "fine"
    assert report.outcome == "not_needed"


def test_close_releases_the_session() -> None:
    session = FakeSession()
    recovery = BrowserRecovery(factory_from(session))
    recovery.session

    recovery.close()

    assert session.closed is True


def test_default_probe_detects_a_dead_page() -> None:
    assert default_probe(FakeSession(alive=True)) is True
    assert default_probe(FakeSession(alive=False)) is False


# --- the real browser ------------------------------------------------------


def _real_factory(tmp_path: Path, profile):
    def factory():
        driver = BrowserDriver(
            profile_dir=tmp_path / "browser-profile",
            artifacts=ArtifactStore(base_dir=tmp_path / "runs", run_name=profile.name),
        ).start()
        provider = WebChatProvider(driver, profile)
        session = type("Session", (), {})()
        session.driver = driver
        session.provider = provider
        session.close = driver.close
        return session

    return factory


def test_a_crashed_page_is_restarted_and_the_task_continues(
    tmp_path: Path, fixture_site, mock_profile
) -> None:
    """Browser crash: the page dies mid-run, recovery restarts it."""
    profile = mock_profile
    recovery = BrowserRecovery(_real_factory(tmp_path, profile), max_restarts=1)
    try:
        first = recovery.session
        first.provider.open()
        assert recovery.is_alive() is True

        # Crash the page the way a browser crash looks to the driver.
        first.driver.close()
        assert recovery.is_alive() is False

        report = recovery.ensure_ready()
        assert report.recovered is True, report.render()

        # The task can continue: the restarted page still answers.
        second = recovery.session
        second.provider.open()
        second.provider.send("after the crash")
        second.provider.wait_until_complete(timeout_ms=20_000)
        captured = second.provider.capture_response()
        assert "after the crash" in captured.text
    finally:
        recovery.close()


def test_an_expired_login_is_recovered_manually(
    tmp_path: Path, fixture_site, mock_profile
) -> None:
    """Login expired: the page shows a wall until a human signs in."""
    profile = mock_profile.model_copy(
        update={
            "url": mock_profile.url + "?login=1",
            "ready_selector": "#login-wall, #composer",
        }
    )
    recovery = BrowserRecovery(
        _real_factory(tmp_path, profile), login_timeout_ms=10_000
    )
    try:
        session = recovery.session
        session.provider.open()
        assert session.provider.is_logged_in() is False

        # Simulate the human signing in inside the headed window.
        session.driver.page.evaluate(
            "() => window.setTimeout("
            "() => document.getElementById('login-button').click(), 600)"
        )

        report = recovery.ensure_logged_in(timeout_ms=10_000)

        assert report.recovered is True, report.render()
        assert session.provider.is_logged_in() is True
    finally:
        recovery.close()


def test_recovery_call_survives_a_real_crash(tmp_path: Path, fixture_site, mock_profile) -> None:
    """The full 'crash mid-call -> recover -> continue' path on a real page."""
    recovery = BrowserRecovery(_real_factory(tmp_path, mock_profile), max_restarts=1)
    try:
        session = recovery.session
        session.provider.open()

        def ask(session):
            if not recovery.is_alive():
                raise RuntimeError("the page is gone")
            session.provider.send("survive this")
            session.provider.wait_until_complete(timeout_ms=20_000)
            return session.provider.capture_response().text

        # break the page, then let call() notice and recover
        session.driver.close()
        value, report = recovery.call(ask)

        assert report.failed is False, report.render()
        assert value is not None and "survive this" in value
    finally:
        recovery.close()
