"""ProviderAdapter contract.

docs/browser.md requires at least: open / send / wait_until_complete /
capture_response / is_logged_in / recover_session. Concrete providers keep
all site-specific detail (selectors, URLs) inside profiles, so nothing about
a provider leaks into future agent code.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone

from .artifacts import ArtifactStore
from .driver import BrowserDriver
from .errors import LoginRequiredError
from .models import (
    BrowserArtifacts,
    CapturedText,
    CompletionTimeline,
    ProviderProfile,
    ProviderReply,
)


class ProviderAdapter(abc.ABC):
    """Base class for web-LLM providers."""

    def __init__(self, driver: BrowserDriver, profile: ProviderProfile) -> None:
        self.driver = driver
        self.profile = profile
        self.artifacts: ArtifactStore = driver.artifacts

    @property
    def name(self) -> str:
        return self.profile.name

    # -- required operations ----------------------------------------------

    @abc.abstractmethod
    def open(self, new_conversation: bool = False) -> None:
        """Open the provider page and wait until it is interactive.

        'new_conversation' is the explicit request for a fresh thread. Without
        it a provider that is already on the site continues the conversation it
        is in, which is what a person does between two questions.
        """

    @abc.abstractmethod
    def send(self, prompt: str) -> None:
        """Type the prompt into the page and submit it."""

    @abc.abstractmethod
    def wait_until_complete(self, timeout_ms: int | None = None) -> CompletionTimeline:
        """Wait for generation to finish (multi-signal, timeout fallback)."""

    @abc.abstractmethod
    def capture_response(self) -> CapturedText:
        """Read the reply (network/SSE > copy button > DOM)."""

    @abc.abstractmethod
    def is_logged_in(self) -> bool:
        """Whether the page currently exposes an authenticated session."""

    @abc.abstractmethod
    def recover_session(self, timeout_ms: int | None = None) -> bool:
        """Re-open the page and wait for a MANUAL login when needed."""

    # -- shared composition ------------------------------------------------

    def after_reply(self) -> None:
        """Hook: called once a reply has been captured.

        The default does nothing; a provider overrides it to remember where the
        conversation now lives, so the next question continues it.
        """

    def ask(
        self,
        prompt: str,
        timeout_ms: int | None = None,
        new_conversation: bool = False,
    ) -> ProviderReply:
        """Full acceptance path: send -> wait -> capture -> save artifacts.

        The returned reply text is page content: DATA, never instructions.
        """
        started = datetime.now(timezone.utc)
        if new_conversation:
            self.open(new_conversation=True)
        if not self.is_logged_in():
            raise LoginRequiredError(
                f"profile '{self.name}' is not logged in; run the login command "
                "and sign in manually in the headed browser window"
            )
        self.send(prompt)
        timeline = self.wait_until_complete(timeout_ms)
        captured = self.capture_response()
        self.after_reply()
        artifacts = self.save_artifacts(
            label=self.profile.name, timeline=timeline, captured=captured
        )
        finished = datetime.now(timezone.utc)
        return ProviderReply(
            text=captured.text,
            source=captured.source,
            completed=timeline.completed,
            timed_out=timeline.timed_out,
            duration_ms=int((finished - started).total_seconds() * 1000),
            timeline=timeline,
            artifacts=artifacts,
            network_urls=captured.network_urls,
        )

    def save_artifacts(
        self,
        label: str,
        timeline: CompletionTimeline | None = None,
        captured: CapturedText | None = None,
    ) -> BrowserArtifacts:
        """Persist screenshot + DOM snapshot (+ optional logs) for this run."""
        self.driver.screenshot(label=f"{label}-screenshot")
        self.driver.dom_snapshot(label=f"{label}-dom")
        if timeline is not None:
            path = self.artifacts.write_json(
                f"{label}-timeline.json", timeline.model_dump(mode="json")
            )
            self.artifacts.logs.append(str(path))
        if captured is not None:
            path = self.artifacts.write_json(
                f"{label}-reply.json", captured.model_dump(mode="json")
            )
            self.artifacts.logs.append(str(path))
        network = self.driver.network()
        path = self.artifacts.write_json(
            f"{label}-network.json",
            [entry.model_dump(mode="json") for entry in network],
        )
        self.artifacts.logs.append(str(path))
        return self.artifacts.collect()

    def close(self) -> None:
        self.driver.close()
