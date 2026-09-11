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
import re
import time
from datetime import datetime, timezone
from typing import Any

from .driver import BrowserDriver
from .errors import LoginRequiredError, ProviderError
from .human import HumanActor
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
        # Network responses seen before the current send: capture uses it so a
        # later question never re-reads an earlier answer's stream.
        self._capture_since = 0
        # The page is driven the way a person drives it (typing rhythm, pointer
        # movement, pauses), see app/browser/human.py.
        self.human = HumanActor(driver.page, profile.human)
        # Where the conversation lives, so a later question continues it.
        self._conversation_url: str | None = None
        self.reused_conversation = False
        # Which default modes this provider has switched on (see apply_toggles).
        self.toggles_on: list[str] = []

    # -- required operations ----------------------------------------------

    def open(self, new_conversation: bool = False) -> None:
        """Open the page, or continue the conversation already open.

        A person asking a second question does not start a new chat: they type
        into the thread they are in. So the default is to REUSE the page when it
        is already on this site with a usable composer, and to navigate back to
        the remembered conversation URL when the page drifted somewhere else.

        'new_conversation=True' is the deliberate fresh start, and is what a
        caller asks for when it wants one.
        """
        selector = self.profile.ready_selector or self.profile.input_selector
        if not new_conversation and self._can_reuse(selector):
            self.reused_conversation = True
            self._remember()
            self.apply_toggles()
            return
        target = self._target_url(new_conversation)
        self.driver.navigate(target)
        if not self.driver.wait_for_selector(selector):
            raise ProviderError(
                f"page never became ready: '{selector}' not visible at " + target
            )
        self.reused_conversation = False
        self._remember()
        self.apply_toggles()

    # -- default modes -----------------------------------------------------

    def apply_toggles(self) -> list[str]:
        """Switch on the profile's pre-send modes (a site's thinking mode).

        A page remembers whatever the last person left behind, so 'the toggle
        exists' is not the same as 'the mode is on'. This checks the ON marker
        and clicks the control when it is missing, then waits for the marker to
        appear so a silent click failure is not mistaken for success.
        """
        applied: list[str] = []
        for toggle in self.profile.toggles:
            if not toggle.enabled:
                continue
            if not self.driver.is_visible(toggle.selector):
                continue
            if toggle.active_selector and self.driver.is_visible(toggle.active_selector):
                continue
            page = self.driver.page
            if not self.human.click(page.locator(toggle.selector).last):
                raise ProviderError(
                    "could not switch on '" + toggle.name + "' (" + toggle.selector + ")"
                )
            if toggle.active_selector and not self.driver.wait_for_selector(
                toggle.active_selector, timeout_ms=5_000
            ):
                raise ProviderError(
                    "'" + toggle.name + "' did not report itself as on after the click"
                )
            applied.append(toggle.name)
        self.toggles_on = sorted(set(self.toggles_on) | set(applied))
        return applied

    # -- conversation continuity ------------------------------------------

    @staticmethod
    def _origin(url: str) -> str:
        match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*://[^/]+)", url or "")
        return match.group(1).lower() if match else ""

    def _can_reuse(self, selector: str) -> bool:
        """True when the open page is this site and already usable."""
        if not self.profile.reuse_conversation:
            return False
        current = self.driver.page_url() or ""
        wanted = self._origin(self.profile.url)
        if not wanted or self._origin(current) != wanted:
            return False
        return self.driver.is_visible(selector)

    def _target_url(self, new_conversation: bool) -> str:
        if new_conversation or not self.profile.reuse_conversation:
            return self.profile.url
        return self._conversation_url or self.profile.url

    def _remember(self) -> None:
        url = self.driver.page_url() or ""
        if url:
            self._conversation_url = url

    def after_reply(self) -> None:
        """Remember where the conversation ended up, and let the page settle."""
        self._remember()
        self.human.settle()

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
        self._capture_since = self.driver.network_cursor()
        try:
            composer = page.locator(self.profile.input_selector).last
            # Move to the composer, click it, clear the draft, then type the
            # message - or PASTE it when it is long, which is what a person does
            # with a multi-kilobyte prompt (app/browser/human.py). With the
            # policy disabled this is a single fill.
            self.human.compose(composer, text)
            if self.profile.send_button_selector:
                self.human.click(page.locator(self.profile.send_button_selector).last)
            else:
                self.human.press_key(composer, self.profile.send_key)
        except Exception as exc:
            raise ProviderError(f"could not send the prompt: {exc}") from exc

    def ask_stream(
        self,
        prompt: str,
        on_delta,
        timeout_ms: int | None = None,
        new_conversation: bool = False,
    ):
        """ask(), reporting the answer WHILE the page writes it.

        Not a second implementation: the completion detector already polls the
        page every poll_interval_ms, so that same loop is what reports the text
        as it grows. A separate loop that waited for a fixed budget made every
        question take completion.timeout_ms (found by asking a real question
        through the console: a 10 second answer took three minutes to surface).
        """
        return self.ask(
            prompt,
            timeout_ms=timeout_ms,
            new_conversation=new_conversation,
            on_delta=on_delta,
        )

    def wait_until_complete(
        self, timeout_ms: int | None = None, on_delta=None
    ) -> CompletionTimeline:
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

        emitted = ""

        def report(text: str) -> None:
            """Hand the new part of the answer to the caller, if any."""
            nonlocal emitted
            if on_delta is None or not text:
                return
            if text.startswith(emitted) and len(text) > len(emitted):
                on_delta(text[len(emitted):], False)
                emitted = text
            elif not text.startswith(emitted):
                # the page replaced the node instead of extending it
                on_delta(text, True)
                emitted = text

        # Phase 1: wait until the page visibly starts generating.
        while time.monotonic() < start_deadline:
            stop_visible = self._stop_visible()
            text = self._dom_text()
            report(text)
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
            report(text)
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
        # The answer element contains page chrome (a code block's language label
        # and its copy/download buttons) and code blocks whose rendered text has
        # folded indentation; the profile says how to read both correctly.
        return self.driver.answer_text(
            self.profile.assistant_message_selector,
            ignore_selectors=self.profile.ignore_selectors,
            code_block_selector=self.profile.code_block_selector,
        )

    def _capture_from_network(self) -> CapturedText | None:
        patterns = self.profile.network_response_patterns
        if not patterns:
            return None
        self.driver.wait_for_request_finished(
            patterns,
            timeout_ms=min(self.profile.completion.poll_interval_ms * 8, 4_000),
            since=self._capture_since,
        )
        chunks: list[str] = []
        urls: list[str] = []
        for entry in self.driver.network(
            url_patterns=patterns,
            content_types=self.profile.network_content_types,
            finished_only=True,
            since=self._capture_since,
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
            target = page.locator(selector).last
            if not self.human.click(target):
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
