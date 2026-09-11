"""Human-like interaction and conversation reuse in the browser layer.

Everything here runs WITHOUT a browser: a fake page records what the actor did,
so the timing rules can be asserted exactly, with a seeded RNG and no waiting.
The real page behaviour is covered by tests/test_browser_driver.py and by the
manual checks under tests/manual/.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.browser.artifacts import ArtifactStore
from app.browser.human import HumanActor
from app.browser.models import HumanPolicy, ProviderProfile
from app.browser.web_chat import WebChatProvider


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeKeyboard:
    def __init__(self, page: "FakePage") -> None:
        self.page = page
        self.typed: list[str] = []

    def type(self, char: str) -> None:
        self.typed.append(char)
        self.page.value += char


class FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float, int]] = []
        self.downs = 0
        self.ups = 0

    def move(self, x: float, y: float, steps: int = 1) -> None:
        self.moves.append((round(float(x), 1), round(float(y), 1), steps))

    def down(self) -> None:
        self.downs += 1

    def up(self) -> None:
        self.ups += 1


class FakeLocator:
    def __init__(self, page: "FakePage", selector: str, box: dict | None = None) -> None:
        self.page = page
        self.selector = selector
        self.box = box
        self.filled: list[str] = []
        self.presses: list[str] = []

    @property
    def last(self) -> "FakeLocator":
        return self

    def bounding_box(self) -> dict | None:
        return self.box

    def click(self) -> None:
        self.page.clicks.append(self.selector)

    def fill(self, text: str) -> None:
        self.filled.append(text)
        self.page.value = text

    def press(self, key: str) -> None:
        self.presses.append(key)
        if key == "Backspace":
            self.page.value = ""
        elif key == "Enter":
            self.page.sent.append(self.page.value)


class FakePage:
    def __init__(self) -> None:
        self.keyboard = FakeKeyboard(self)
        self.mouse = FakeMouse()
        self.locators: dict[str, FakeLocator] = {}
        self.waits: list[int] = []
        self.clicks: list[str] = []
        self.sent: list[str] = []
        self.value = ""
        self.url = "about:blank"

    def locator(self, selector: str) -> FakeLocator:
        if selector not in self.locators:
            box = {"x": 100.0, "y": 200.0, "width": 400.0, "height": 40.0}
            self.locators[selector] = FakeLocator(self, selector, box)
        return self.locators[selector]

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str, arg=None):
        return [0.0, 0.0]


class FakeDriver:
    """Only the surface WebChatProvider touches."""

    def __init__(self, tmp_path: Path, url: str = "http://127.0.0.1:8765/") -> None:
        self.page = FakePage()
        self.page.url = url
        self.artifacts = ArtifactStore(base_dir=tmp_path / "runs", run_name="probe")
        self.navigations: list[str] = []
        self.visible: dict[str, bool] = {}
        self.ready: dict[str, bool] = {}
        self.artifacts_run = 0
        self.context = None

    # -- driver surface ----------------------------------------------------

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
        return self.ready.get(selector, True)

    def last_text(self, selector: str, timeout_ms: int = 2_000) -> str:
        return ""

    def network_cursor(self) -> int:
        return 0

    def network(self, **kwargs):
        return []

    def wait_for_request_finished(self, patterns, timeout_ms: int = 4_000, since: int = 0):
        return None

    def screenshot(self, label: str = "screenshot", full_page: bool = True) -> Path:
        path = self.artifacts.next_path(label, ".png")
        path.write_bytes(b"\x89PNG")
        self.artifacts.screenshots.append(str(path))
        return path

    def dom_snapshot(self, label: str = "dom"):
        from app.browser.models import DomSnapshot

        snapshot = DomSnapshot(url=self.page.url, title="fake")
        return snapshot

    def click_last(self, selector: str, timeout_ms: int = 5_000) -> bool:
        self.page.clicks.append(selector)
        return True


def make_profile(**kwargs) -> ProviderProfile:
    payload = {
        "name": "fake-site",
        "url": "https://chat.example/",
        "input_selector": "textarea",
        "assistant_message_selector": "div.answer",
    }
    payload.update(kwargs)
    return ProviderProfile.model_validate(payload)


def fast_policy(typing: tuple[int, int] = (1, 4), chance: float = 1.0, **kwargs) -> HumanPolicy:
    """A coherent, quick policy: 'typing' is the (fastest, slowest) band."""
    low, high = typing
    span = max(high - low, 1)
    payload = {
        "typing_min_ms": low,
        "typing_fast_max_ms": low + span // 3,
        "typing_slow_min_ms": low + (2 * span) // 3,
        "typing_max_ms": high,
        "typing_fast_chance": chance,
        "key_pause_chance": 0,
        # 0/0 means the pause does not happen at all
        "think_min_ms": 0,
        "think_max_ms": 0,
        "pre_send_min_ms": 0,
        "pre_send_max_ms": 1,
        "settle_min_ms": 0,
        "settle_max_ms": 1,
        "mouse_max_ms": 0,
        "click_hold_ms": 0,
    }
    payload.update(kwargs)
    return HumanPolicy.model_validate(payload)


# ---------------------------------------------------------------------------
# the policy
# ---------------------------------------------------------------------------


def test_the_policy_is_enabled_by_default() -> None:
    assert HumanPolicy().enabled is True


def test_a_policy_can_be_switched_off_for_a_local_page() -> None:
    assert HumanPolicy(enabled=False).enabled is False


@pytest.mark.parametrize(
    "low,high",
    [
        ("typing_min_ms", "typing_max_ms"),
        ("think_min_ms", "think_max_ms"),
        ("pre_send_min_ms", "pre_send_max_ms"),
        ("settle_min_ms", "settle_max_ms"),
        ("key_pause_min_ms", "key_pause_max_ms"),
    ],
)
def test_an_inverted_range_is_refused(low: str, high: str) -> None:
    with pytest.raises(ValueError):
        HumanPolicy(**{low: 500, high: 100})


def test_a_profile_carries_the_policy_and_reuse_by_default() -> None:
    profile = make_profile()
    assert profile.human.enabled is True
    assert profile.reuse_conversation is True


# ---------------------------------------------------------------------------
# the actor
# ---------------------------------------------------------------------------


def test_typing_is_character_by_character_with_variable_pauses() -> None:
    page = FakePage()
    actor = HumanActor(page, fast_policy(typing=(10, 40)), random.Random(7))

    actor.type_text(page.locator("textarea"), "hello")

    assert page.keyboard.typed == list("hello"), "every character was typed in order"
    assert len(page.waits) == 5, "exactly one pause per character"
    assert all(10 <= wait <= 40 for wait in page.waits), page.waits
    assert actor.summary()["actions"]["typed_chars"] == 1


def test_typing_is_a_mixture_of_fast_and_slow_not_one_flat_range() -> None:
    page = FakePage()
    policy = HumanPolicy(
        typing_min_ms=10,
        typing_fast_max_ms=20,
        typing_slow_min_ms=100,
        typing_max_ms=200,
        typing_fast_chance=0.7,
        think_min_ms=0,
        think_max_ms=0,
        key_pause_chance=0,
    )
    actor = HumanActor(page, policy, random.Random(11))

    actor.type_text(page.locator("textarea"), "a" * 120)

    delays = page.waits
    fast = [value for value in delays if value <= 20]
    slow = [value for value in delays if value >= 100]
    assert len(fast) + len(slow) == 120, "every delay came from one of the two bands"
    assert len(fast) > len(slow), "most characters are typed fast"
    assert slow, "some characters are typed slowly"
    assert all(10 <= value <= 200 for value in delays)


def test_the_average_typing_speed_is_quick() -> None:
    page = FakePage()
    actor = HumanActor(page, HumanPolicy(), random.Random(4))
    delays = [actor.typing_delay() for _ in range(400)]
    average = sum(delays) / len(delays)
    assert average < 70, "the default rhythm must not be uniformly slow: " + str(average)
    assert min(delays) >= HumanPolicy().typing_min_ms
    assert max(delays) <= HumanPolicy().typing_max_ms


def test_the_fast_band_can_be_tuned_to_always_slow() -> None:
    page = FakePage()
    policy = HumanPolicy(typing_fast_chance=0.0)
    actor = HumanActor(page, policy, random.Random(6))
    delays = [actor.typing_delay() for _ in range(50)]
    assert all(value >= policy.typing_slow_min_ms for value in delays)


def test_an_inverted_typing_band_is_refused() -> None:
    with pytest.raises(ValueError):
        HumanPolicy(typing_fast_max_ms=300, typing_slow_min_ms=100)
    with pytest.raises(ValueError):
        HumanPolicy(typing_min_ms=200, typing_fast_max_ms=50)


def test_the_summary_reports_the_rhythm_it_used() -> None:
    page = FakePage()
    actor = HumanActor(
        page,
        HumanPolicy(
            typing_min_ms=10,
            typing_fast_max_ms=20,
            typing_slow_min_ms=100,
            typing_max_ms=200,
            think_min_ms=0,
            think_max_ms=0,
            key_pause_chance=0,
        ),
        random.Random(9),
    )
    actor.type_text(page.locator("textarea"), "a" * 20)

    summary = actor.summary()
    assert summary["characters"]["fast"] + summary["characters"]["slow"] == 20
    assert summary["typing_band_ms"] == [10, 20, 100, 200]


def test_typing_pauses_longer_on_word_boundaries() -> None:
    page = FakePage()
    policy = fast_policy(typing=(10, 10), key_pause_min_ms=200, key_pause_max_ms=200)
    actor = HumanActor(page, policy, random.Random(1))

    actor.type_text(page.locator("textarea"), "a b")

    # the boundary pause ADDS to the typing delay: a, then the space (10 + 200), then b
    assert page.waits == [10, 10, 200, 10], page.waits


def test_the_pause_lands_in_the_configured_range() -> None:
    page = FakePage()
    actor = HumanActor(page, fast_policy(), random.Random(3))
    values = [actor.pause(50, 60) for _ in range(20)]
    assert all(50 <= value <= 60 for value in values)
    assert len(set(values)) > 1, "the pause is not a fixed constant"


def test_a_disabled_policy_fills_instead_of_typing() -> None:
    page = FakePage()
    actor = HumanActor(page, HumanPolicy(enabled=False))

    actor.type_text(page.locator("textarea"), "hello")

    assert page.keyboard.typed == []
    assert page.locator("textarea").filled == ["hello"]


def test_the_pointer_moves_in_segments_and_then_clicks() -> None:
    page = FakePage()
    actor = HumanActor(page, fast_policy(mouse_steps=8), random.Random(5))

    assert actor.click(page.locator("textarea")) is True

    assert len(page.mouse.moves) == 2, "an approach move and a precise move"
    assert page.mouse.moves[0][2] == 8
    assert page.mouse.downs == 1 and page.mouse.ups == 1
    x, y, _ = page.mouse.moves[-1]
    assert 100 <= x <= 500 and 200 <= y <= 240, "the point is inside the element"


def test_clicking_falls_back_when_there_is_no_box() -> None:
    page = FakePage()
    locator = FakeLocator(page, "textarea", box=None)
    actor = HumanActor(page, fast_policy())

    assert actor.click(locator) is True
    assert page.clicks == ["textarea"]


def test_clearing_the_composer_selects_all_then_deletes() -> None:
    page = FakePage()
    page.value = "an old draft"
    actor = HumanActor(page, fast_policy())

    actor.clear(page.locator("textarea"))

    assert page.locator("textarea").presses == ["Control+a", "Backspace"]
    assert page.value == ""


def test_composing_moves_the_mouse_click_and_then_types() -> None:
    page = FakePage()
    actor = HumanActor(page, fast_policy(typing=(1, 2)), random.Random(2))

    actor.compose(page.locator("textarea"), "hi")

    assert page.mouse.downs == 1 and page.mouse.ups == 1, "the composer was clicked"
    assert page.mouse.moves, "the pointer travelled to it"
    assert "".join(page.keyboard.typed) == "hi"
    assert page.value == "hi"
    actions = actor.summary()["actions"]
    assert actions["move"] == 1 and actions["click"] == 1 and actions["typed_chars"] == 1


def test_composing_with_the_policy_off_fills_in_one_step() -> None:
    page = FakePage()
    actor = HumanActor(page, HumanPolicy(enabled=False))

    actor.compose(page.locator("textarea"), "hello")

    assert page.locator("textarea").filled == ["hello"]
    assert page.mouse.downs == 0 and page.keyboard.typed == []


def test_pressing_send_pauses_first() -> None:
    page = FakePage()
    page.value = "hello"
    actor = HumanActor(page, fast_policy(pre_send_min_ms=5, pre_send_max_ms=5))

    actor.press_key(page.locator("textarea"), "Enter")

    assert page.locator("textarea").presses == ["Enter"]
    assert 5 in actor.page.waits


def test_the_summary_reports_what_happened() -> None:
    page = FakePage()
    actor = HumanActor(page, fast_policy())
    actor.type_text(page.locator("textarea"), "hi")
    assert actor.summary()["actions"]["typed_chars"] == 1
    assert actor.summary()["enabled"] is True


# ---------------------------------------------------------------------------
# conversation reuse
# ---------------------------------------------------------------------------


def test_the_first_open_navigates(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.page.url = "about:blank"
    provider = WebChatProvider(driver, make_profile())

    provider.open()

    assert driver.navigations == ["https://chat.example/"]
    assert provider.reused_conversation is False


def test_a_second_open_reuses_the_open_conversation(tmp_path: Path) -> None:
    """A person asking twice does not start two chats."""
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(driver, make_profile())

    provider.open()
    provider.open()

    assert driver.navigations == ["https://chat.example/"], "the page was not reloaded"
    assert provider.reused_conversation is True


def test_reuse_is_remembered_when_the_page_was_already_there(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.page.url = "https://chat.example/a/chat/s/abc123"
    provider = WebChatProvider(driver, make_profile())

    provider.open()

    assert driver.navigations == []
    assert provider.reused_conversation is True


def test_a_new_conversation_is_explicit(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(driver, make_profile())
    provider.open()
    provider.open(new_conversation=True)

    assert driver.navigations == ["https://chat.example/", "https://chat.example/"]
    assert provider.reused_conversation is False


def test_a_page_on_another_site_is_not_reused(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.page.url = "https://example.com/somewhere"
    provider = WebChatProvider(driver, make_profile())

    provider.open()

    assert driver.navigations == ["https://chat.example/"]
    assert provider.reused_conversation is False


def test_a_page_without_a_composer_is_not_reused(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.page.url = "https://chat.example/"
    driver.visible["textarea"] = False
    provider = WebChatProvider(driver, make_profile())

    provider.open()

    assert driver.navigations == ["https://chat.example/"], "it went back to the site"
    assert provider.reused_conversation is False


def test_a_profile_can_refuse_reuse(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(driver, make_profile(reuse_conversation=False))
    provider.open()
    provider.open()

    assert driver.navigations == ["https://chat.example/", "https://chat.example/"]
    assert provider.reused_conversation is False


def test_the_conversation_url_is_remembered_after_a_reply(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(driver, make_profile())
    provider.open()

    driver.page.url = "https://chat.example/a/chat/s/abc123"
    provider.after_reply()
    assert provider._conversation_url.endswith("abc123")

    # a page that drifted away comes back to the SAME conversation
    driver.page.url = "about:blank"
    provider.open()
    assert driver.navigations[-1] == "https://chat.example/a/chat/s/abc123"


def test_sending_to_a_reused_conversation_types_like_a_person(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(driver, make_profile(human=fast_policy(typing=(1, 2))))
    provider.open()

    provider.send("ping")

    composer = driver.page.locator("textarea")
    assert driver.page.mouse.downs == 1, "the composer was clicked like a person clicks it"
    assert composer.presses[:2] == ["Control+a", "Backspace"], "the draft was cleared first"
    assert "".join(driver.page.keyboard.typed) == "ping"
    assert composer.presses[-1] == "Enter"
    assert driver.page.sent == ["ping"]


def test_sending_raises_when_the_page_never_becomes_ready(tmp_path: Path) -> None:
    from app.browser.errors import ProviderError

    driver = FakeDriver(tmp_path)
    driver.visible["textarea"] = False
    driver.ready["textarea"] = False
    provider = WebChatProvider(driver, make_profile())

    with pytest.raises(ProviderError):
        provider.open()


# ---------------------------------------------------------------------------
# pre-send toggles (a site's thinking mode)
# ---------------------------------------------------------------------------

THINKING = {
    "name": "深度思考",
    "selector": "div.toggle:has-text('深度思考')",
    "active_selector": "div.toggle[aria-pressed='true']",
}


def test_a_toggle_that_is_off_is_switched_on(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = True
    driver.visible[THINKING["active_selector"]] = False
    provider = WebChatProvider(driver, make_profile(toggles=[THINKING]))

    provider.open()

    # a human click: the pointer moved to the control and the button went down
    assert driver.page.mouse.moves, "the pointer travelled to the switch"
    assert driver.page.mouse.downs == 1 and driver.page.mouse.ups == 1
    assert provider.toggles_on == ["深度思考"]


def test_a_toggle_that_is_already_on_is_left_alone(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = True
    driver.visible[THINKING["active_selector"]] = True
    provider = WebChatProvider(driver, make_profile(toggles=[THINKING]))

    provider.open()

    assert driver.page.mouse.downs == 0, "an already-on switch is not clicked"
    assert provider.toggles_on == []


def test_a_toggle_the_page_does_not_have_is_skipped(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = False
    provider = WebChatProvider(driver, make_profile(toggles=[THINKING]))

    provider.open()

    assert driver.page.mouse.downs == 0
    assert provider.toggles_on == []


def test_a_disabled_toggle_is_never_clicked(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = True
    driver.visible[THINKING["active_selector"]] = False
    provider = WebChatProvider(
        driver, make_profile(toggles=[dict(THINKING, enabled=False)])
    )

    provider.open()

    assert driver.page.mouse.downs == 0
    assert provider.toggles_on == []


def test_a_toggle_that_does_not_report_back_is_an_error(tmp_path: Path) -> None:
    """A click that silently fails must not look like success."""
    from app.browser.errors import ProviderError

    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = True
    driver.visible[THINKING["active_selector"]] = False
    driver.ready[THINKING["active_selector"]] = False
    provider = WebChatProvider(driver, make_profile(toggles=[THINKING]))

    with pytest.raises(ProviderError) as caught:
        provider.open()
    assert "深度思考" in str(caught.value)


def test_toggles_are_applied_to_a_reused_conversation_too(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    driver.visible[THINKING["selector"]] = True
    driver.visible[THINKING["active_selector"]] = False
    provider = WebChatProvider(driver, make_profile(toggles=[THINKING]))

    provider.open()
    provider.open()

    assert provider.reused_conversation is True
    assert provider.toggles_on == ["深度思考"]


def test_the_thinking_switch_can_be_declared_as_a_profile_default() -> None:
    profile = make_profile(
        toggles=[dict(THINKING, description="reasoning mode", enabled=True)]
    )
    assert profile.toggles[0].name == "深度思考"
    assert profile.toggles[0].active_selector.endswith("aria-pressed='true']")


def test_the_shipped_deepseek_profile_thinks_by_default() -> None:
    """The default is asserted against the file that ships, not a copy."""
    from app.browser.profiles import load_profile

    profile = load_profile("deepseek-web")
    assert profile.toggles, "the deepseek profile must carry its thinking switch"
    thinking = profile.toggles[0]
    assert thinking.enabled is True
    assert "深度思考" in thinking.selector
    assert "aria-pressed='true'" in thinking.active_selector
    assert profile.human.typing_fast_chance > 0.5, "typing is mostly fast"


def test_sending_with_human_off_fills_in_one_step(tmp_path: Path) -> None:
    driver = FakeDriver(tmp_path)
    provider = WebChatProvider(
        driver, make_profile(human=HumanPolicy(enabled=False))
    )
    provider.open()
    provider.send("ping")

    assert driver.page.locator("textarea").filled == ["ping"]
    assert driver.page.keyboard.typed == []
