"""Human-like interaction for the browser layer.

Two things this is and one thing it is not.

It IS:

* a **pacing** layer - a page reacts differently when a form is filled
  instantly and submitted in the same millisecond than when a person moves the
  mouse, clicks, types with a variable rhythm and then presses Enter;
* **honest use of the page**: the same clicks and keystrokes a person would
  make, nothing else.

It is NOT a stealth layer. There is no fingerprint patching, no navigator
spoofing, no captcha solving and no risk-control evasion - all of those are
forbidden by the project's rules, and none of them appear here.

Every delay has a deterministic injection point (the RNG), so a test can pin the
timing without sleeping for real.
"""

from __future__ import annotations

import random
from typing import Any, Protocol

from .models import HumanPolicy


class SupportsPause(Protocol):  # pragma: no cover - typing aid
    def wait_for_timeout(self, ms: int) -> None: ...


class HumanActor:
    """Drive a page the way a person would: move, click, type, pause."""

    def __init__(
        self,
        page: Any,
        policy: HumanPolicy | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.page = page
        self.policy = policy or HumanPolicy()
        self.rng = rng or random.Random()
        # What actually happened, for the run log and for tests.
        self.events: list[tuple[str, Any]] = []

    # -- timing ------------------------------------------------------------

    def pause(self, low_ms: int, high_ms: int) -> int:
        """Wait a random number of milliseconds inside the given range."""
        if high_ms <= 0 and low_ms <= 0:
            return 0
        wait = self.rng.randint(min(low_ms, high_ms), max(low_ms, high_ms))
        if wait > 0:
            self.page.wait_for_timeout(wait)
        return wait

    def think(self) -> int:
        """The pause before starting to type."""
        return self.pause(self.policy.think_min_ms, self.policy.think_max_ms)

    def settle(self) -> int:
        """The pause after a reply is captured, before the next action."""
        return self.pause(self.policy.settle_min_ms, self.policy.settle_max_ms)

    # -- pointer -----------------------------------------------------------

    def point_for(self, box: dict[str, float]) -> tuple[float, float]:
        """A point inside the element, biased to the middle like a real cursor."""
        width = max(float(box.get("width", 1)), 1.0)
        height = max(float(box.get("height", 1)), 1.0)
        x = float(box.get("x", 0)) + width * self.rng.uniform(0.30, 0.70)
        y = float(box.get("y", 0)) + height * self.rng.uniform(0.35, 0.65)
        return round(x, 1), round(y, 1)

    def move_to(self, x: float, y: float) -> None:
        """Move the mouse in a couple of eased segments, not one teleport."""
        steps = max(1, self.policy.mouse_steps)
        try:
            start = self.page.evaluate("() => [window.__lastMouseX || 0, window.__lastMouseY || 0]")
            start_x, start_y = float(start[0]), float(start[1])
        except Exception:  # pragma: no cover - a page that refuses evaluation
            start_x, start_y = x - 120, y - 80
        mid_x = start_x + (x - start_x) * self.rng.uniform(0.5, 0.8) + self.rng.uniform(-12, 12)
        mid_y = start_y + (y - start_y) * self.rng.uniform(0.5, 0.8) + self.rng.uniform(-8, 8)
        self.page.mouse.move(mid_x, mid_y, steps=steps)
        self.pause(0, self.policy.mouse_max_ms)
        self.page.mouse.move(x, y, steps=max(2, steps // 2))
        try:
            self.page.evaluate(
                "(p) => { window.__lastMouseX = p[0]; window.__lastMouseY = p[1]; }", [x, y]
            )
        except Exception:  # pragma: no cover
            pass
        self.events.append(("move", (round(x, 1), round(y, 1))))

    def click(self, locator: Any) -> bool:
        """Move to the element, then click it."""
        try:
            box = locator.bounding_box()
        except Exception:  # pragma: no cover - an element that vanished
            box = None
        if not box:
            try:
                locator.click()
                self.events.append(("click", "fallback"))
                return True
            except Exception:
                return False
        x, y = self.point_for(box)
        self.move_to(x, y)
        try:
            self.page.mouse.down()
            self.pause(0, self.policy.click_hold_ms)
            self.page.mouse.up()
        except Exception:  # pragma: no cover - mouse issues surface as a failed click
            return False
        self.events.append(("click", (x, y)))
        return True

    # -- keyboard ----------------------------------------------------------

    def clear(self, locator: Any) -> None:
        """Clear the composer the way a person does: select all, then delete."""
        try:
            locator.press(self.policy.select_all_key)
            self.pause(0, 30)
            locator.press("Backspace")
        except Exception:
            try:
                locator.fill("")
            except Exception:  # pragma: no cover - nothing left to try
                pass

    # -- long text ---------------------------------------------------------

    def should_paste(self, text: str) -> bool:
        """Long text is pasted, not typed - that is what a person does.

        Nobody types three thousand characters one by one, and a page that gets
        thousands of synthetic keystrokes re-renders on every one of them.
        """
        return self.policy.enabled and len(text) >= self.policy.paste_threshold_chars

    def copy_text(self, text: str) -> bool:
        """Put text on the clipboard ('' means the page refused)."""
        try:
            self.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass
        try:
            # the promise MUST be awaited: a fire-and-forget write raced the
            # paste and the composer received nothing (found by a real run, where
            # the fallback then typed a 4800-character prompt character by
            # character - minutes per step)
            result = self.page.evaluate(
                "async (t) => { await navigator.clipboard.writeText(t); return true; }", text
            )
            return bool(result)
        except Exception:
            return False

    def paste(self, locator: Any, text: str) -> bool:
        """Click, clear, paste, and verify the composer really holds the text."""
        try:
            self.click(locator)
            self.think()
            self.clear(locator)
            for _attempt in range(2):
                if not self.copy_text(text):
                    return False
                self.pause(self.policy.paste_min_ms, self.policy.paste_max_ms)
                locator.press(self.policy.paste_key)
                self.pause(self.policy.paste_settle_min_ms, self.policy.paste_settle_max_ms)
                value = self.value_of(locator)
                if value is None or text in value:
                    break
            else:
                return False
        except Exception:
            return False
        self.events.append(("pasted", len(text)))
        return True

    def value_of(self, locator: Any) -> str | None:
        """What the composer currently holds, when the page can say."""
        for reader in ("input_value", "value"):
            method = getattr(locator, reader, None)
            if callable(method):
                try:
                    value = method()
                    return value if isinstance(value, str) else None
                except Exception:
                    return None
        return None

    def compose(self, locator: Any, text: str) -> None:
        """Everything a person does to send a message, in order.

        Move to the composer, click it, clear whatever draft is there, then type
        the message with a variable rhythm. The click matters: a page that never
        receives a pointer event is a page nobody touched.
        """
        if not self.policy.enabled:
            locator.fill(text)
            self.events.append(("fill", len(text)))
            return
        if self.should_paste(text):
            if self.paste(locator, text):
                return
            # A paste that cannot be made to work must not turn into minutes of
            # typing: fill the composer and record that the human path was
            # skipped, instead of pretending the slow path is the same thing.
            try:
                locator.fill(text)
                self.events.append(("fill_after_failed_paste", len(text)))
                return
            except Exception:
                pass
        self.click(locator)
        self.think()
        self.clear(locator)
        self.type_text(locator, text)

    def typing_delay(self) -> int:
        """One character's delay, from a fast band and a slow band.

        People type in bursts: most characters fly by, and a few - at a word
        boundary, mid-thought, or after a typo - take noticeably longer. A flat
        range around one average is the one thing a human rhythm never looks
        like, so this is a mixture, not a uniform draw.
        """
        policy = self.policy
        if self.rng.random() < policy.typing_fast_chance:
            return self.rng.randint(policy.typing_min_ms, policy.typing_fast_max_ms)
        return self.rng.randint(policy.typing_slow_min_ms, policy.typing_max_ms)

    def type_text(self, locator: Any, text: str) -> None:
        """Type character by character with a variable rhythm.

        Each character gets a fast-or-slow delay, and a pause lands on word
        boundaries and punctuation, which is what a person's typing looks like.
        """
        if not self.policy.enabled:
            locator.fill(text)
            self.events.append(("fill", len(text)))
            return
        self.think()
        fast = 0
        slow = 0
        for char in text:
            self._type_char(char)
            delay = self.typing_delay()
            if delay <= self.policy.typing_fast_max_ms:
                fast += 1
            else:
                slow += 1
            self.pause(delay, delay)
            boundary = char in self.policy.pause_characters
            if boundary or self.rng.random() < self.policy.key_pause_chance:
                self.pause(self.policy.key_pause_min_ms, self.policy.key_pause_max_ms)
        self.events.append(("typed_chars", len(text)))
        self.events.append(("typing_rhythm", (fast, slow)))

    def _type_char(self, char: str) -> None:
        self.page.keyboard.type(char)

    def press_key(self, locator: Any, key: str) -> None:
        """A human pause, then the key."""
        self.pause(self.policy.pre_send_min_ms, self.policy.pre_send_max_ms)
        locator.press(key)
        self.events.append(("press", key))

    # -- reporting ---------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for name, _value in self.events:
            counts[name] = counts.get(name, 0) + 1
        rhythm = next(
            (value for name, value in self.events if name == "typing_rhythm"), None
        )
        summary = {
            "enabled": self.policy.enabled,
            "actions": counts,
            "typing_band_ms": [
                self.policy.typing_min_ms,
                self.policy.typing_fast_max_ms,
                self.policy.typing_slow_min_ms,
                self.policy.typing_max_ms,
            ],
            "typing_fast_chance": self.policy.typing_fast_chance,
        }
        if rhythm:
            summary["characters"] = {"fast": rhythm[0], "slow": rhythm[1]}
        return summary
