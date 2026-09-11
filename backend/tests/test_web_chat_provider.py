"""WebChatProvider tests: full acceptance path, completion signals, capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.errors import LoginRequiredError, ProviderError
from app.browser.web_chat import WebChatProvider
from tests.conftest import make_driver

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PROMPT = "hello m1"


def _provider(driver, profile) -> WebChatProvider:
    return WebChatProvider(driver, profile)


def _expected(prompt: str = PROMPT) -> str:
    return f"Fixture reply to: {prompt}"


# ---------------------------------------------------------------------------
# Acceptance path: open -> send -> wait -> capture -> screenshot + DOM
# ---------------------------------------------------------------------------


def test_acceptance_path_saves_reply_screenshot_and_dom(driver, mock_profile) -> None:
    provider = _provider(driver, mock_profile)

    provider.open()
    assert provider.is_logged_in() is True

    reply = provider.ask(PROMPT, timeout_ms=20_000)

    assert reply.completed is True
    assert reply.timed_out is False
    assert reply.text == _expected()
    assert reply.source in {"network", "clipboard", "dom"}
    assert reply.duration_ms > 0

    assert reply.artifacts.screenshots, "a screenshot must be saved"
    assert reply.artifacts.dom_snapshots, "a DOM snapshot must be saved"

    screenshot = Path(reply.artifacts.screenshots[0])
    dom = Path(reply.artifacts.dom_snapshots[0])
    assert screenshot.exists() and screenshot.read_bytes()[:8] == PNG_MAGIC
    assert dom.exists() and "messages" in dom.read_text(encoding="utf-8")
    assert Path(reply.artifacts.run_dir) == driver.artifacts.run_dir
    assert reply.artifacts.logs, "timeline/reply/network logs are written"


def test_completion_timeline_reports_multiple_signals(driver, mock_profile) -> None:
    provider = _provider(driver, mock_profile)
    provider.open()
    provider.send(PROMPT)

    timeline = provider.wait_until_complete(timeout_ms=20_000)

    assert timeline.completed is True
    assert timeline.timed_out is False
    assert timeline.generation_started is True
    assert timeline.polls > 0
    assert timeline.stable_polls >= mock_profile.completion.stable_polls
    assert timeline.text_length == len(_expected())
    assert "generation_started" in timeline.signals
    assert "dom_stable" in timeline.signals
    assert timeline.duration_ms > 0


def test_a_second_question_does_not_replay_the_first_answer(driver, mock_profile) -> None:
    """The network capture must be scoped to the current exchange."""
    provider = _provider(driver, mock_profile)
    provider.open()

    provider.send("first question")
    provider.wait_until_complete(timeout_ms=20_000)
    first = provider.capture_response()

    provider.send("second question")
    provider.wait_until_complete(timeout_ms=20_000)
    second = provider.capture_response()

    assert first.text == "Fixture reply to: first question"
    assert second.text == "Fixture reply to: second question"
    assert "first question" not in second.text, "the earlier answer leaked into this one"


def test_capture_prefers_network_over_dom(driver, mock_profile) -> None:
    # The assistant selector points nowhere, so any text must come from the
    # network stream: this proves the documented capture priority.
    profile = mock_profile.model_copy(
        update={"assistant_message_selector": "#no-such-element"}
    )
    provider = _provider(driver, profile)

    provider.open()
    provider.send(PROMPT)
    provider.wait_until_complete(timeout_ms=20_000)
    captured = provider.capture_response()

    assert captured.source == "network"
    assert captured.text == _expected()
    assert captured.network_urls and "/api/chat" in captured.network_urls[0]


def test_capture_falls_back_to_dom(driver, mock_profile) -> None:
    profile = mock_profile.model_copy(
        update={
            "network_response_patterns": [],
            "copy_button_selector": None,
            "copy_status_selector": None,
        }
    )
    provider = _provider(driver, profile)

    provider.open()
    provider.send(PROMPT)
    provider.wait_until_complete(timeout_ms=20_000)
    captured = provider.capture_response()

    assert captured.source == "dom"
    assert captured.text == _expected()


# ---------------------------------------------------------------------------
# Failure and timeout paths
# ---------------------------------------------------------------------------


def test_timeout_fallback_returns_partial_text(driver, mock_profile) -> None:
    profile = mock_profile.model_copy(
        update={"url": f"{mock_profile.url}?mode=stuck"}
    )
    provider = _provider(driver, profile)
    provider.open()

    reply = provider.ask(PROMPT, timeout_ms=4_000)

    assert reply.completed is False
    assert reply.timed_out is True
    assert reply.text, "partial text must still be returned"
    assert reply.text in _expected()
    assert reply.timeline.stop_button_seen is True, (
        "the visible stop control must block a false completion"
    )
    assert "timeout_fallback" in reply.timeline.signals
    assert reply.artifacts.screenshots


def test_generation_that_never_starts_times_out(driver, mock_profile) -> None:
    profile = mock_profile.model_copy(
        update={
            "completion": mock_profile.completion.model_copy(
                update={"start_timeout_ms": 1_200, "timeout_ms": 5_000}
            )
        }
    )
    provider = _provider(driver, profile)
    provider.open()

    timeline = provider.wait_until_complete()

    assert timeline.completed is False
    assert timeline.timed_out is True
    assert timeline.generation_started is False
    assert "the page never started generating" in timeline.note


def test_empty_prompt_is_refused(driver, mock_profile) -> None:
    provider = _provider(driver, mock_profile)
    provider.open()

    with pytest.raises(ProviderError):
        provider.send("   ")


def test_open_fails_when_page_never_becomes_ready(tmp_path: Path, mock_profile, fixture_site) -> None:
    driver = make_driver(tmp_path, default_timeout_ms=1_500)
    try:
        profile = mock_profile.model_copy(update={"ready_selector": "#no-such-element"})
        provider = _provider(driver, profile)
        with pytest.raises(ProviderError):
            provider.open()
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Login handling (manual by design)
# ---------------------------------------------------------------------------


def _login_profile(mock_profile, driver):
    # ready_selector must match the login wall as well, because #composer is
    # hidden while the wall is up.
    return mock_profile.model_copy(
        update={
            "url": f"{mock_profile.url}?login=1",
            "ready_selector": "#login-wall, #composer",
        }
    )


def test_login_wall_blocks_sending(driver, mock_profile) -> None:
    provider = _provider(driver, _login_profile(mock_profile, driver))
    provider.open()

    assert provider.is_logged_in() is False
    with pytest.raises(LoginRequiredError) as excinfo:
        provider.send(PROMPT)
    assert excinfo.value.code == "login_required"


def test_recover_session_waits_for_manual_login(driver, mock_profile) -> None:
    provider = _provider(driver, _login_profile(mock_profile, driver))
    provider.open()
    assert provider.is_logged_in() is False

    # Simulate the human signing in inside the headed window.
    driver.page.evaluate(
        "() => window.setTimeout("
        "() => document.getElementById('login-button').click(), 800)"
    )

    assert provider.recover_session(timeout_ms=10_000) is True
    assert provider.is_logged_in() is True

    reply = provider.ask(PROMPT, timeout_ms=20_000)
    assert reply.completed is True
    assert reply.text == _expected()


def test_recover_session_times_out_without_login(driver, mock_profile) -> None:
    provider = _provider(driver, _login_profile(mock_profile, driver))
    provider.open()

    with pytest.raises(LoginRequiredError) as excinfo:
        provider.recover_session(timeout_ms=1_500)
    assert "still shows a login wall" in str(excinfo.value)


def test_ask_refuses_when_not_logged_in(driver, mock_profile) -> None:
    provider = _provider(driver, _login_profile(mock_profile, driver))
    provider.open()

    with pytest.raises(LoginRequiredError):
        provider.ask(PROMPT, timeout_ms=5_000)
