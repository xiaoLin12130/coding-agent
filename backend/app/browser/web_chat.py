"""The single M1 provider: a selector-driven web chat page.

One implementation, many profiles. The provider only knows the operations
from ProviderAdapter; every site-specific value (URL, selectors, network
patterns) comes from a ProviderProfile.

Completion detection uses multiple signals (docs/browser.md):
stop control gone + DOM stable + text length stable, with a timeout
fallback that returns whatever was captured.

Reply capture priority (docs/browser.md): network/SSE > copy button > DOM.

Reminder: everything read from the page is DATA. It is parsed defensively and
never executed or treated as an instruction.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from .driver import BrowserDriver
from .errors import LoginRequiredError, ProviderError
from .models import CapturedResponse, CapturedText, CompletionTimeline
from .provider import ProviderAdapter

MANUAL_LOGIN_TIMEOUT_MS = 300_000


class WebChatProvider(ProviderAdapter):
    """Generic provider for a web chat page described by a profile."""

    def __init__(
        self,
        driver: BrowserDriver,
        profile,  # ProviderProfile
    ) -> None:
        super().__init__(driver, profile)
        self._last_timeline: CompletionTimeline | None = None

    # -- required operations ----------------------------------------------

    def open(self) -> None:
        self.driver.navigate(self.profile.url)
        selector = self.profile.ready_selector or self.profile.input_selector
        if not self.driver.wait_for_selector(selector):
            raise ProviderError(
                f"page never became ready: '{selector}' not visible at "
                f"{self.profile.url}"
            )

    def is_logged_in(self) -> bool:
        if self.driver.is_visible(self.profile.login_required_selector):
            return False
        if self.profile.login_indicator_selector:
            return self.driver.is_visible(self.profile.login_indicator_selector)
        return self.driver.is_visible(self.profile.input_selector)

    def recover_session(self, timeout_ms: int | None = None) -> bool:
        """Re-open the page and wait for a MANUAL login.

        Credentials, captcha and risk-control flows are never automated; the
        human signs in inside the headed browser window and the persistent
        profile keeps the session for later runs.
        """
        ready = self.profile.ready_selector or self.profile.input_selector
        if not self.driver.is_visible(ready) and not self.driver.is_visible(
            self.profile.login_required_selector
        ):
            self.open()
        if self.is_logged_in():
            return True
        budget = MANUAL_LOGIN_TIMEOUT_MS if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + budget / 1000
        signal = (
            self.profile.login_indicator_selector
            or self.profile.input_selector
        )
        while time.monotonic() < deadline:
            if self.is_logged_in():
                return True
            self.driver.wait(500)
        raise LoginRequiredError(
            f"profile '{self.name}' still shows a login wall after {budget} ms; "
            f"sign in manually in the headed window until '{signal}' is visible"
        )

    def send(self, prompt: str) -> None:
        text = (prompt or "").strip()
        if not text:
            raise ProviderError("prompt must not be empty")
        if not self.is_logged_in():
            raise LoginRequiredError(
                f"profile '{self.name}' is not logged in; log in manually first"
            )
        page = self.driver.page
        try:
            composer = page.locator(self.profile.input_selector).last
            composer.click()
            composer.fill(text)
            if self.profile.send_button_selector:
                page.locator(self.profile.send_button_selector).last.click()
            else:
                composer.press(self.profile.send_key)
        except Exception as exc:
            raise ProviderError(f"could not send the prompt: {exc}") from exc

    def wait_until_complete(self, timeout_ms: int | None = None) -> CompletionTimeline:
        policy = self.profile.completion
        budget = policy.timeout_ms if timeout_ms is None else timeout_ms
        started_at = datetime.now(timezone.utc)
        start = time.monotonic()
        deadline = start + budget / 1000
        start_deadline = start + policy.start_timeout_ms / 1000

        signals: list[str] = []
        polls = 0
        stable = 0
        last_len = -1
        stop_seen = False
        generation_started = False

        # Phase 1: wait until the page visibly starts generating.
        while time.monotonic() < start_deadline:
            stop_visible = self._stop_visible()
            text = self._dom_text()
            if stop_visible or len(text) > 0:
                generation_started = True
                stop_seen = stop_seen or stop_visible
                signals.append("generation_started")
                break
            self.driver.wait(policy.poll_interval_ms)

        if not generation_started:
            return self._timeline(
                started_at,
                completed=False,
                timed_out=True,
                generation_started=False,
                polls=polls,
                stable=stable,
                stop_seen=stop_seen,
                text_length=0,
                signals=signals,
                note="the page never started generating within start_timeout_ms",
            )

        # Phase 2: multi-signal completion detection.
        while time.monotonic() < deadline:
            text = self._dom_text()
            length = len(text)
            stop_visible = self._stop_visible()
            stop_seen = stop_seen or stop_visible
            polls += 1

            if text and not stop_visible and length == last_len:
                stable += 1
            else:
                stable = 0
            last_len = length

            elapsed_ms = int((time.monotonic() - start) * 1000)
            if stable >= policy.stable_polls and elapsed_ms >= policy.min_wait_ms:
                signals.append("stop_button_gone")
                signals.append("dom_stable")
                signals.append("text_length_stable")
                return self._timeline(
                    started_at,
                    completed=True,
                    timed_out=False,
                    generation_started=True,
                    polls=polls,
                    stable=stable,
                    stop_seen=stop_seen,
                    text_length=length,
                    signals=signals,
                    note="completion detected by multi-signal agreement",
                )

            self.driver.wait(policy.poll_interval_ms)

        signals.append("timeout_fallback")
        return self._timeline(
            started_at,
            completed=False,
            timed_out=True,
            generation_started=True,
            polls=polls,
            stable=stable,
            stop_seen=stop_seen,
            text_length=max(last_len, 0),
            signals=signals,
            note=f"no completion within {budget} ms; returning partial text",
        )

    def capture_response(self) -> CapturedText:
        captured = self._capture_from_network()
        if captured is not None and captured.text:
            return captured

        clipboard = self._capture_from_clipboard()
        if clipboard:
            return CapturedText(text=clipboard, source="clipboard")

        return CapturedText(text=self._dom_text(), source="dom")

    # -- internals ---------------------------------------------------------

    def _stop_visible(self) -> bool:
        return self.driver.is_visible(self.profile.stop_button_selector)

    def _dom_text(self) -> str:
        return self.driver.last_text(self.profile.assistant_message_selector)

    def _capture_from_network(self) -> CapturedText | None:
        patterns = self.profile.network_response_patterns
        if not patterns:
            return None
        self.driver.wait_for_request_finished(
            patterns, timeout_ms=min(self.profile.completion.poll_interval_ms * 8, 4_000)
        )
        chunks: list[str] = []
        urls: list[str] = []
        for entry in self.driver.network(
            url_patterns=patterns,
            content_types=self.profile.network_content_types,
            finished_only=True,
        ):
            body = self.driver.read_body(entry)
            if not body:
                continue
            text = self._extract_text(body, entry)
            if text:
                chunks.append(text)
                urls.append(entry.url)
        if not chunks:
            return None
        return CapturedText(text="".join(chunks), source="network", network_urls=urls)

    def _extract_text(self, body: str, entry: CapturedResponse) -> str:
        path = self.profile.network_text_path
        if "event-stream" in entry.content_type:
            pieces: list[str] = []
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload in ("", "[DONE]"):
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                value = self._dig(data, path)
                if isinstance(value, str):
                    pieces.append(value)
            return "".join(pieces)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return ""
        value = self._dig(data, path)
        return value if isinstance(value, str) else ""

    @staticmethod
    def _dig(data: Any, path: str) -> Any:
        node = data
        for part in path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            elif isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
            if node is None:
                return None
        return node

    def _capture_from_clipboard(self) -> str:
        selector = self.profile.copy_button_selector
        if not selector:
            return ""
        page = self.driver.page
        try:
            self.driver.context.grant_permissions(
                ["clipboard-read", "clipboard-write"]
            )
        except Exception:
            pass
        try:
            if not self.driver.click_last(selector):
                return ""
            if self.profile.copy_status_selector:
                self.driver.wait_for_selector(
                    self.profile.copy_status_selector, timeout_ms=2_000
                )
            else:
                self.driver.wait(200)
            value = page.evaluate("() => navigator.clipboard.readText()")
            return value.strip() if isinstance(value, str) else ""
        except Exception:
            return ""

    def _timeline(
        self,
        started_at: datetime,
        completed: bool,
        timed_out: bool,
        generation_started: bool,
        polls: int,
        stable: int,
        stop_seen: bool,
        text_length: int,
        signals: list[str],
        note: str,
    ) -> CompletionTimeline:
        finished = datetime.now(timezone.utc)
        timeline = CompletionTimeline(
            started_at=started_at,
            finished_at=finished,
            duration_ms=int((finished - started_at).total_seconds() * 1000),
            completed=completed,
            timed_out=timed_out,
            generation_started=generation_started,
            polls=polls,
            stable_polls=stable,
            stop_button_seen=stop_seen,
            text_length=text_length,
            signals=signals,
            note=note,
        )
        self._last_timeline = timeline
        return timeline
