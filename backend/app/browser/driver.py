"""Playwright browser driver.

M1 requirements implemented here: headed browser, persistent profile, page
open, screenshot and DOM snapshot. The driver itself knows nothing about any
specific web LLM; that is the provider's job.

The browser is ALWAYS headed (docs/browser.md). No stealth/fingerprint
patches, no credential automation, no captcha or risk-control bypass.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..config import browser_profile_dir
from .artifacts import ArtifactStore
from .errors import BrowserConfigError, BrowserError
from .models import (
    BrowserArtifacts,
    CapturedResponse,
    DomSnapshot,
    path_str,
)

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}


class BrowserDriver:
    """Owns one Playwright persistent context and one page."""

    def __init__(
        self,
        profile_dir: Path | str | None = None,
        viewport: dict[str, int] | None = None,
        artifacts: ArtifactStore | None = None,
        default_timeout_ms: int = 30_000,
        slow_mo_ms: int = 0,
        headless: bool = False,
        browser: str = "chromium",
    ) -> None:
        if headless:
            raise BrowserConfigError(
                "M1 requires a headed browser (docs/browser.md); "
                "headless mode is refused."
            )
        self.profile_dir = (
            Path(profile_dir) if profile_dir is not None else browser_profile_dir()
        )
        self.viewport = dict(viewport or DEFAULT_VIEWPORT)
        self.artifacts = artifacts if artifacts is not None else ArtifactStore()
        self.default_timeout_ms = default_timeout_ms
        self.slow_mo_ms = slow_mo_ms
        self.browser_name = browser

        self._playwright = None
        self._context = None
        self._page = None
        self._responses: list[CapturedResponse] = []
        self._response_objects: dict[str, object] = {}
        self._finished_urls: set[str] = set()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "BrowserDriver":
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        browser_type = getattr(self._playwright, self.browser_name)
        try:
            self._context = browser_type.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                viewport=self.viewport,
                slow_mo=self.slow_mo_ms,
            )
        except Exception as exc:
            self.close()
            message = str(exc)
            if "Target page, context or browser has been closed" in message or (
                "existing browser session" in message
            ):
                # Chromium refuses a second instance on a user-data-dir it
                # already owns, and the failure surfaces as a closed target.
                raise BrowserError(
                    "the browser profile "
                    + str(self.profile_dir)
                    + " is already in use by another process; close that browser "
                    "(or use a different profile directory) and retry"
                ) from exc
            raise BrowserError(
                f"could not launch {self.browser_name}: {exc}"
            ) from exc
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)
        self._page.on("response", self._on_response)
        self._page.on("requestfinished", self._on_request_finished)
        self._page.on("requestfailed", self._on_request_finished)
        return self

    def close(self) -> None:
        for closer in (self._context, self._playwright):
            if closer is None:
                continue
            try:
                closer.close() if hasattr(closer, "close") else closer.stop()
            except Exception:
                pass
        self._context = None
        self._playwright = None
        self._page = None

    def __enter__(self) -> "BrowserDriver":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- page accessors ----------------------------------------------------

    @property
    def context(self):
        if self._context is None:
            raise BrowserError("driver is not started; call start() first")
        return self._context

    @property
    def page(self):
        if self._page is None:
            raise BrowserError("driver is not started; call start() first")
        return self._page

    def navigate(self, url: str, wait_until: str = "domcontentloaded"):
        return self.page.goto(url, wait_until=wait_until)

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)

    def page_url(self) -> str:
        return self.page.url

    def page_title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ""

    def is_visible(self, selector: str | None, timeout_ms: int = 1_000) -> bool:
        if not selector:
            return False
        try:
            return bool(self.page.locator(selector).last.is_visible(timeout=timeout_ms))
        except Exception:
            return False

    def wait_for_selector(
        self, selector: str, timeout_ms: int | None = None, state: str = "visible"
    ) -> bool:
        try:
            self.page.wait_for_selector(
                selector,
                timeout=self.default_timeout_ms if timeout_ms is None else timeout_ms,
                state=state,
            )
            return True
        except Exception:
            return False

    def last_text(
        self,
        selector: str,
        timeout_ms: int = 2_000,
        ignore_selectors: list[str] | None = None,
    ) -> str:
        """Text of the last element matching selector ('' when absent).

        'ignore_selectors' are hidden for the duration of the read, so chrome
        rendered INSIDE the answer (a code block's language label and its copy
        button) does not become part of the reply. Hiding and restoring is used
        instead of cloning because innerText of a detached node has no layout.
        """
        try:
            locator = self.page.locator(selector)
            count = locator.count()
            if count == 0:
                return ""
            if not ignore_selectors:
                return locator.nth(count - 1).inner_text(timeout=timeout_ms).strip()
            text = self.page.evaluate(
                """(args) => {
                    const nodes = document.querySelectorAll(args.selector);
                    if (!nodes.length) return "";
                    const node = nodes[nodes.length - 1];
                    const hidden = [];
                    for (const sel of args.ignore) {
                        for (const el of node.querySelectorAll(sel)) {
                            hidden.push([el, el.style.display]);
                            el.style.display = "none";
                        }
                    }
                    let text = "";
                    try {
                        text = node.innerText || "";
                    } finally {
                        for (const [el, previous] of hidden) el.style.display = previous;
                    }
                    return text.trim();
                }""",
                {"selector": selector, "ignore": list(ignore_selectors)},
            )
            return text if isinstance(text, str) else ""
        except Exception:
            return ""

    def answer_text(
        self,
        selector: str,
        ignore_selectors: list[str] | None = None,
        code_block_selector: str | None = None,
    ) -> str:
        """The answer as text, with code blocks read EXACTLY.

        innerText is the rendered text: inside a code block the page's own
        styling can fold the leading whitespace of every line, so a captured
        Python file came back with one space of indentation instead of four and
        the agent wrote files that would not even import. A code block's
        textContent is the real text, so each block is read that way and the
        rest of the answer still comes from innerText.
        """
        if not code_block_selector:
            return self.last_text(selector, ignore_selectors=ignore_selectors)
        try:
            text = self.page.evaluate(
                """(args) => {
                    const nodes = document.querySelectorAll(args.selector);
                    if (!nodes.length) return "";
                    const node = nodes[nodes.length - 1];
                    const hidden = [];
                    for (const sel of args.ignore) {
                        for (const el of node.querySelectorAll(sel)) {
                            hidden.push([el, el.style.display]);
                            el.style.display = "none";
                        }
                    }
                    let out = "";
                    try {
                        const children = node.children.length ? Array.from(node.children) : [node];
                        const parts = [];
                        for (const child of children) {
                            const isCode = child.matches && child.matches(args.code);
                            const block = isCode ? child : (child.querySelector ? child.querySelector(args.code) : null);
                            const pre = block && block.querySelector ? block.querySelector("pre") : null;
                            if (pre && pre.textContent.trim()) {
                                parts.push(pre.textContent.replace(/\n+$/, ""));
                            } else {
                                const text = child.innerText || "";
                                if (text.trim()) parts.push(text);
                            }
                        }
                        out = parts.join("\n\n");
                    } finally {
                        for (const [el, previous] of hidden) el.style.display = previous;
                    }
                    return out.trim();
                }""",
                {
                    "selector": selector,
                    "ignore": list(ignore_selectors or []),
                    "code": code_block_selector,
                },
            )
            return text if isinstance(text, str) else ""
        except Exception:
            return self.last_text(selector, ignore_selectors=ignore_selectors)

    def click_last(self, selector: str, timeout_ms: int = 5_000) -> bool:
        try:
            locator = self.page.locator(selector)
            count = locator.count()
            if count == 0:
                return False
            locator.nth(count - 1).click(timeout=timeout_ms)
            return True
        except Exception:
            return False

    # -- artifacts ---------------------------------------------------------

    def screenshot(self, label: str = "screenshot", full_page: bool = True) -> Path:
        path = self.artifacts.next_path(label, ".png")
        self.page.screenshot(path=str(path), full_page=full_page)
        self.artifacts.screenshots.append(str(path))
        return path

    def dom_snapshot(self, label: str = "dom") -> DomSnapshot:
        html = self.page.content()
        html_path = self.artifacts.next_path(label, ".html")
        html_path.write_text(html, encoding="utf-8")
        try:
            text = self.page.evaluate(
                "() => (document.body ? document.body.innerText : '')"
            )
        except Exception:
            text = ""
        text_path = self.artifacts.next_path(label, ".txt")
        text_path.write_text(text or "", encoding="utf-8")
        self.artifacts.dom_snapshots.append(str(html_path))
        return DomSnapshot(
            url=self.page_url(),
            title=self.page_title(),
            captured_at=datetime.now(timezone.utc),
            html_path=path_str(html_path),
            text_path=path_str(text_path),
            html_bytes=len(html.encode("utf-8")),
            text_chars=len(text or ""),
        )

    # -- network capture ---------------------------------------------------

    def _on_response(self, response) -> None:
        try:
            headers = response.headers or {}
            entry = CapturedResponse(
                url=response.url,
                status=int(response.status),
                content_type=str(headers.get("content-type", "")),
            )
            self._responses.append(entry)
            self._response_objects[entry.url] = response
        except Exception:
            return

    def _on_request_finished(self, request) -> None:
        try:
            self._finished_urls.add(request.url)
        except Exception:
            return

    def network_cursor(self) -> int:
        """Index of the next response; pass it as 'since' to ignore earlier ones."""
        return len(self._responses)

    def network(
        self,
        url_patterns: list[str] | None = None,
        content_types: list[str] | None = None,
        finished_only: bool = False,
        since: int = 0,
    ) -> list[CapturedResponse]:
        entries = []
        for index, entry in enumerate(self._responses):
            # 'since' is what keeps a second question on the same page from
            # being answered with the first question's responses as well.
            if index < since:
                continue
            if url_patterns and not any(
                re.search(pattern, entry.url) for pattern in url_patterns
            ):
                continue
            if content_types and not any(
                kind in entry.content_type for kind in content_types
            ):
                continue
            finished = entry.url in self._finished_urls
            if finished_only and not finished:
                continue
            entries.append(entry.model_copy(update={"finished": finished}))
        return entries

    def read_body(self, entry: CapturedResponse) -> str:
        """Read a captured response body.

        Only called for responses whose request already finished, so this
        never blocks on an open stream.
        """
        response = self._response_objects.get(entry.url)
        if response is None:
            return ""
        try:
            return response.text()
        except Exception:
            return ""

    def wait_for_request_finished(
        self,
        url_patterns: list[str],
        timeout_ms: int = 2_000,
        poll_ms: int = 100,
        since: int = 0,
    ) -> bool:
        waited = 0
        while waited < timeout_ms:
            candidates = {
                entry.url for index, entry in enumerate(self._responses) if index >= since
            }
            if any(
                re.search(pattern, url)
                for pattern in url_patterns
                for url in self._finished_urls
                if url in candidates
            ):
                return True
            self.wait(poll_ms)
            waited += poll_ms
        return False
