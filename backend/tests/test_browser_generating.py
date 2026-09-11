"""M14: never send a question into an answer that is still being written.

The live failure this pins: an answer that PAUSES (the model thinking, or a long
block not rendered yet) has a stable text length, so the old completion detector
declared it finished, the agent sent the next prompt, and the site replaced the
answer in flight. What arrived was a truncated tool call, which the parser then
rejected ("invalid json"), and the run ended with the project half-edited.

The fix has two halves, both tested here against a fake page:

* "still generating" is decided by the PAGE, not by a text heuristic - an
  in-flight request to the site's completion endpoint (or the stop control,
  when a profile names one);
* send() waits for the page to settle and refuses to interrupt it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.errors import ProviderError
from app.browser.models import ProviderProfile
from app.browser.web_chat import WebChatProvider

COMPLETION = "https://chat.example/api/v0/chat/completion"


class FakePage:
    def __init__(self) -> None:
        self.waits: list[int] = []
        self.value = ""
        self.clicks: list[str] = []
        self.mouse = type("Mouse", (), {"move": lambda *a, **k: None, "down": lambda *a: None, "up": lambda *a: None})()
        self.keyboard = type("Keyboard", (), {"type": lambda *a, **k: None})()
        self.context = type("Context", (), {"grant_permissions": lambda *a, **k: None})()

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script, arg=None):
        return [0.0, 0.0]

    def locator(self, selector: str):
        return FakeLocator(self, selector)


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def last(self) -> "FakeLocator":
        return self

    def bounding_box(self):
        return {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0}

    def click(self) -> None:
        self.page.clicks.append(self.selector)

    def fill(self, text: str) -> None:
        self.page.value = text

    def input_value(self) -> str:
        return self.page.value

    def press(self, key: str) -> None:
        if key == "Control+a":
            pass
        elif key == "Backspace":
            self.page.value = ""
        elif key == "Enter":
            self.page.sent.append(self.page.value)


class FakeDriver:
    """A page whose text and network state are scripted by the test."""

    def __init__(self, texts: list[str] | None = None, generating: list[bool] | None = None) -> None:
        self.page = FakePage()
        self.page.sent = []
        self.page.url = "https://chat.example/"
        self.texts = list(texts or [""])
        self.generating_sequence = list(generating or [False])
        self.text_calls = 0
        self.generating_calls = 0
        self.visible: dict[str, bool] = {}
        self.artifacts = None
        self.navigations: list[str] = []
        self.offline_flights: list[bool] = []

    # -- scripted state ----------------------------------------------------

    def _next_text(self) -> str:
        index = min(self.text_calls, len(self.texts) - 1)
        self.text_calls += 1
        return self.texts[index]

    def _next_generating(self) -> bool:
        index = min(self.generating_calls, len(self.generating_sequence) - 1)
        self.generating_calls += 1
        return self.generating_sequence[index]

    # -- driver surface ----------------------------------------------------

    @property
    def generating(self) -> bool:
        return self._next_generating()

    def inflight(self, url_patterns=None) -> list[str]:
        if not self._next_generating():
            return []
        return [COMPLETION]

    def navigate(self, url: str, wait_until: str = "domcontentloaded"):
        self.navigations.append(url)
        self.page.url = url

    def wait(self, ms: int) -> None:
        self.page.waits.append(ms)

    def page_url(self) -> str:
        return self.page.url

    def is_visible(self, selector, timeout_ms: int = 1_000) -> bool:
        if not selector:
            return False
        return self.visible.get(selector, True)

    def wait_for_selector(self, selector, timeout_ms=None, state: str = "visible") -> bool:
        return self.visible.get(selector, True)

    def last_text(self, selector: str, timeout_ms: int = 2_000) -> str:
        return self._next_text()

    def answer_text(self, selector: str, ignore_selectors=None, code_block_selector=None) -> str:
        return self._next_text()

    def network_cursor(self) -> int:
        return 0

    def network(self, **kwargs):
        return []

    def wait_for_request_finished(self, patterns, timeout_ms: int = 4_000, since: int = 0):
        return None

    def click_last(self, selector: str, timeout_ms: int = 5_000) -> bool:
        self.page.clicks.append(selector)
        return True

    def screenshot(self, label: str = "screenshot", full_page: bool = True) -> Path:
        return Path("shot.png")

    def dom_snapshot(self, label: str = "dom"):
        return None


def make_profile(**kwargs) -> ProviderProfile:
    payload = {
        "name": "fake-site",
        "url": "https://chat.example/",
        "input_selector": "textarea",
        "assistant_message_selector": "div.answer",
        "generating_patterns": ["/api/v0/chat/completion"],
        "human": {"enabled": False},
        "completion": {
            "timeout_ms": 2_000,
            "start_timeout_ms": 500,
            "poll_interval_ms": 1,
            "stable_polls": 2,
            "min_wait_ms": 0,
            "idle_timeout_ms": 50,
        },
    }
    payload.update(kwargs)
    return ProviderProfile.model_validate(payload)


def provider(driver: FakeDriver, **profile_kwargs) -> WebChatProvider:
    return WebChatProvider(driver, make_profile(**profile_kwargs))


# --- the signal ------------------------------------------------------------


def test_an_in_flight_completion_request_means_still_generating() -> None:
    driver = FakeDriver(generating=[True, False])
    chat = provider(driver)
    assert chat.is_generating() is True
    assert chat.is_generating() is False


def test_the_stop_control_also_means_still_generating() -> None:
    driver = FakeDriver(generating=[False])
    driver.visible[".stop"] = True
    chat = provider(driver, stop_button_selector=".stop")
    assert chat.is_generating() is True


def test_an_unrelated_request_is_not_generating() -> None:
    class Other(FakeDriver):
        def inflight(self, url_patterns=None):
            return [] if not url_patterns else []

    chat = provider(Other(generating=[False]))
    assert chat.is_generating() is False


# --- sending ---------------------------------------------------------------


def test_send_waits_for_the_page_to_settle() -> None:
    driver = FakeDriver(generating=[True, True, False])
    chat = provider(driver)
    chat.send("next question")
    assert driver.page.sent == ["next question"]
    assert driver.page.waits, "it waited instead of typing straight away"


def test_send_refuses_to_interrupt_a_page_that_never_settles() -> None:
    driver = FakeDriver(generating=[True])
    chat = provider(driver)
    with pytest.raises(ProviderError) as caught:
        chat.send("next question")
    assert "still generating" in str(caught.value)
    assert driver.page.sent == [], "nothing was typed into the running answer"


def test_a_guard_that_gives_up_does_not_type_anything() -> None:
    """The whole point: an interrupted answer is worse than no answer."""
    driver = FakeDriver(generating=[True])
    chat = provider(driver, completion={**make_profile().completion.model_dump(), "idle_timeout_ms": 5})
    with pytest.raises(ProviderError):
        chat.send("do not interrupt")
    assert driver.page.sent == []
    assert driver.page.value == ""


# --- completion detection --------------------------------------------------


def test_a_paused_answer_is_not_a_finished_one() -> None:
    """Stable text + a live request = still generating, so keep waiting."""
    driver = FakeDriver(
        texts=["", "part one", "part one", "part one", "part one", "part one complete"],
        generating=[True, True, True, True, True, False, False],
    )
    chat = provider(driver, completion={"timeout_ms": 5_000, "start_timeout_ms": 500,
                                        "poll_interval_ms": 1, "stable_polls": 2,
                                        "min_wait_ms": 0, "idle_timeout_ms": 50})
    timeline = chat.wait_until_complete()
    assert timeline.completed is True
    assert "still_generating" in timeline.signals
    assert timeline.text_length == len("part one complete"), "it captured the whole answer"


def test_completion_reports_when_it_gave_up_on_a_live_answer() -> None:
    driver = FakeDriver(texts=["partial"], generating=[True])
    chat = provider(driver, completion={"timeout_ms": 6, "start_timeout_ms": 500,
                                        "poll_interval_ms": 1, "stable_polls": 2,
                                        "min_wait_ms": 0, "idle_timeout_ms": 5})
    timeline = chat.wait_until_complete()
    assert timeline.completed is False and timeline.timed_out is True
    assert "still_generating" in timeline.signals
    assert "STILL generating" in timeline.note


def test_an_in_flight_request_counts_as_generation_started() -> None:
    """Thinking mode: no text for seconds, but the answer is on its way."""
    driver = FakeDriver(texts=["", "", "answer"], generating=[True, True, True, False])
    chat = provider(driver, completion={"timeout_ms": 5_000, "start_timeout_ms": 1,
                                        "poll_interval_ms": 1, "stable_polls": 2,
                                        "min_wait_ms": 0, "idle_timeout_ms": 50})
    timeline = chat.wait_until_complete()
    assert timeline.generation_started is True
    assert "the page never started generating" not in timeline.note


# --- the shipped profile ----------------------------------------------------


def test_the_deepseek_profile_watches_the_completion_endpoint() -> None:
    from app.browser.profiles import load_profile

    profile = load_profile("deepseek-web")
    assert profile.generating_patterns == ["/api/v0/chat/completion"]
    assert profile.completion.idle_timeout_ms >= 60_000
