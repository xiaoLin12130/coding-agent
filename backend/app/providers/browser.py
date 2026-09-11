"""The browser provider: a web LLM through Playwright (M1/M6).

This is the provider the project ships as its default. It is registered like
every other one, and it hands the loop nothing but a ModelClient - the fact
that a browser is behind it never reaches the AgentLoop.

The model it returns is the console's ConsoleModel: one lazily created,
recoverable browser session (M6 recovery included), so a crashed page or an
expired login does not end the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import ProviderInfo, ProviderOption
from .registry import ProviderRegistry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.llm import ModelClient

INFO = ProviderInfo(
    name="browser",
    kind="browser",
    label="Web LLM (browser)",
    description=(
        "Drive a web LLM page with Playwright. The page is headed by policy and "
        "login is manual; a crashed page or an expired session is recovered by M6."
    ),
    model_label="a web chat page",
    requires_login=True,
    requires_network=True,
    options=[
        ProviderOption(
            name="profile",
            description="Provider profile name from backend/profiles (default: the settings document)",
        ),
        ProviderOption(
            name="artifacts_dir",
            description="Where run artifacts are written (default: runs/)",
        ),
    ],
)


def create(profile: str = "", artifacts_dir: str = "") -> "ModelClient":
    """Build a browser-backed model.

    'profile' and 'artifacts_dir' override the settings document when given, so
    the CLI can run a specific profile without editing anyone's settings.
    """
    from ..console_model import ConsoleModel
    from ..settings import SettingsStore

    store: Any = SettingsStore()
    if profile or artifacts_dir:
        settings = store.load()
        provider = settings.provider
        browser = settings.browser
        if profile:
            provider = provider.model_copy(update={"name": profile})
        if artifacts_dir:
            browser = browser.model_copy(update={"artifacts_dir": artifacts_dir})
        settings = settings.model_copy(update={"provider": provider, "browser": browser})
        store = _FrozenSettings(store, settings)
    return ConsoleModel(store).model()


class _FrozenSettings:
    """A SettingsStore whose load() returns an override (nothing is written)."""

    def __init__(self, inner: Any, settings: Any) -> None:
        self._inner = inner
        self._settings = settings

    def load(self) -> Any:
        return self._settings

    def save(self, settings: Any) -> Any:  # pragma: no cover - never used
        return self._inner.save(settings)

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - passthrough
        return getattr(self._inner, item)


def register(registry: ProviderRegistry) -> None:
    registry.register(INFO, create)
