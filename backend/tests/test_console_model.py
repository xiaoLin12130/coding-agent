"""M11 fix: the console's browser session belongs to ONE thread.

The console starts every run and every question on a new worker thread, and
Playwright's synchronous objects belong to the thread that created them. The
first version built the session on whichever thread ran first, so the second run
died with:

    cannot switch to a different thread (which happens to have exited)

These tests pin the fix with a fake session, so they need no browser.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from app.console_model import BrowserThread, ConsoleModel, ThreadBoundProvider


class FakeProvider:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []
        self.questions: list[str] = []
        self.recoveries = 0
        self.fail_next = 0

    def ask(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        self.thread_ids.append(threading.get_ident())
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("the page died")
        self.questions.append(prompt)
        return type("Reply", (), {"text": "answer: " + prompt})()

    def ask_stream(self, prompt: str, on_delta, *args: Any, **kwargs: Any) -> Any:
        self.thread_ids.append(threading.get_ident())
        on_delta("half ", False)
        on_delta("answer: " + prompt, True)
        return self.ask(prompt)

    def is_logged_in(self) -> bool:
        return True

    def open(self, new_conversation: bool = False) -> None:
        return None

    def recover_session(self, timeout_ms: int | None = None) -> bool:
        self.recoveries += 1
        return True


class FakeSession:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider
        self.closed = False

    def close(self) -> None:
        self.closed = True


def make_browser(provider: FakeProvider) -> BrowserThread:
    return BrowserThread(lambda: FakeSession(provider))


def test_calls_from_different_threads_all_work() -> None:
    """The regression: a second run on a new thread used to fail."""
    provider = FakeProvider()
    browser = make_browser(provider)
    bound = ThreadBoundProvider(browser)
    try:
        results: list[Any] = []

        def run() -> None:
            results.append(bound.ask("first"))

        first = threading.Thread(target=run)
        first.start()
        first.join()
        # a NEW thread, exactly like the runtime does for every run
        second = threading.Thread(target=run)
        second.start()
        second.join()

        assert [reply.text for reply in results] == ["answer: first", "answer: first"]
        assert provider.questions == ["first", "first"]
    finally:
        browser.close()


def test_every_call_runs_on_the_owning_thread() -> None:
    provider = FakeProvider()
    browser = make_browser(provider)
    bound = ThreadBoundProvider(browser)
    try:
        seen: list[int] = []

        def call() -> None:
            seen.append(threading.get_ident())
            bound.ask("x")

        thread = threading.Thread(target=call)
        thread.start()
        thread.join()

        assert provider.thread_ids == [browser.ident], "the call left the browser thread"
        assert seen[0] != browser.ident, "the caller really was another thread"
    finally:
        browser.close()


def test_the_session_is_created_once_and_closed_on_the_owning_thread() -> None:
    provider = FakeProvider()
    created: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession(provider)
        created.append(session)
        return session

    browser = BrowserThread(factory)
    bound = ThreadBoundProvider(browser)
    bound.ask("a")
    bound.ask("b")
    assert len(created) == 1, "the browser must not be relaunched per call"

    browser.close()
    assert created[0].closed is True, "the session is closed when the thread ends"
    with pytest.raises(RuntimeError):
        bound.ask("c")


def test_a_failed_call_is_recovered_once_and_retried() -> None:
    provider = FakeProvider()
    browser = make_browser(provider)
    bound = ThreadBoundProvider(browser)
    try:
        provider.fail_next = 1
        reply = bound.ask("after a crash")
        assert reply.text == "answer: after a crash"
        assert provider.recoveries == 1
    finally:
        browser.close()


def test_a_failure_that_cannot_be_recovered_is_raised() -> None:
    class Dead(FakeProvider):
        def recover_session(self, timeout_ms: int | None = None) -> bool:
            self.recoveries += 1
            return False

    provider = Dead()
    provider.fail_next = 1
    browser = make_browser(provider)
    bound = ThreadBoundProvider(browser)
    try:
        with pytest.raises(RuntimeError):
            bound.ask("doomed")
        assert provider.recoveries == 1, "it tried once, then gave up"
    finally:
        browser.close()


def test_streaming_goes_through_the_same_thread() -> None:
    provider = FakeProvider()
    browser = make_browser(provider)
    bound = ThreadBoundProvider(browser)
    try:
        pieces: list[tuple[str, bool]] = []
        bound.ask_stream("streamed", lambda text, reset: pieces.append((text, reset)))
        assert pieces == [("half ", False), ("answer: streamed", True)]
        # both the streaming call and the ask() the fake performs inside it
        assert provider.thread_ids == [browser.ident, browser.ident]
    finally:
        browser.close()


def test_the_console_model_hands_out_one_model_and_one_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[int] = []

    def factory() -> FakeSession:
        created.append(threading.get_ident())
        return FakeSession(FakeProvider())

    model = ConsoleModel()
    monkeypatch.setattr(model, "_factory", factory)
    first = model.model()
    second = model.model()
    assert first is second, "the model is built once"
    assert model._browser is not None

    model.close()
    assert model._browser is None
    assert created == [], "no browser until a call needs one"
