"""The model the console drives: a real web LLM through the M1/M6 stack.

The console does not get a special model. It gets exactly what the CLI gets —
a BrowserModel over the Playwright provider — wrapped in the M6 BrowserRecovery
so a crashed page or an expired login is recovered instead of killing the run.
"""

from __future__ import annotations

import threading
from typing import Any

from .agents.llm import BrowserModel, ModelClient
from .browser.artifacts import ArtifactStore
from .browser.driver import BrowserDriver
from .browser.profiles import load_profile
from .browser.web_chat import WebChatProvider
from .recovery import BrowserRecovery
from .settings import SettingsStore


class ConsoleModel:
    """A lazily created, recoverable browser session shared by console runs."""

    def __init__(self, settings: SettingsStore | None = None) -> None:
        self.settings_store = settings or SettingsStore()
        self._lock = threading.Lock()
        self._recovery: BrowserRecovery | None = None
        self._model: BrowserModel | None = None

    # -- the session -------------------------------------------------------

    def _factory(self) -> Any:
        settings = self.settings_store.load()
        profile = load_profile(settings.provider.name)
        driver = BrowserDriver(
            profile_dir=settings.browser.profile_dir or None,
            artifacts=ArtifactStore(base_dir=settings.browser.artifacts_dir or None,
                                    run_name=profile.name),
        ).start()
        provider = WebChatProvider(driver, profile)
        session = type("Session", (), {})()
        session.driver = driver
        session.provider = provider
        session.close = driver.close
        return session

    def recovery(self) -> BrowserRecovery:
        with self._lock:
            if self._recovery is None:
                self._recovery = BrowserRecovery(self._factory)
            return self._recovery

    def model(self) -> ModelClient:
        """The ModelClient handed to a run."""
        recovery = self.recovery()
        with self._lock:
            if self._model is None:
                # provider_factory, so a restarted page is picked up
                self._model = BrowserModel(
                    provider_factory=lambda: self._require_provider(recovery)
                )
            return self._model

    def _require_provider(self, recovery: BrowserRecovery) -> Any:
        session = recovery.session
        provider = session.provider
        # Opening is idempotent enough: the provider waits for the page to be
        # ready, and BrowserRecovery restarts a dead one before this runs.
        try:
            if not provider.is_logged_in():
                provider.open()
        except Exception:
            provider.open()
        return provider

    def close(self) -> None:
        with self._lock:
            if self._recovery is not None:
                self._recovery.close()
                self._recovery = None
                self._model = None
