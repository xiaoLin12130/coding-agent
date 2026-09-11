"""Console settings (M8).

One document the Workbench reads and writes: provider, browser, working
directory, safety, confirmation, context thresholds and multi-agent.

Defaults come from the running configuration, so the settings page shows the
truth rather than a second copy of it. Nothing here grants permission: the
safety document only DESCRIBES the policy the SafetyLayer already enforces, and
headless_allowed is pinned false because docs/browser.md requires a headed
browser.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .browser.profiles import list_profiles, load_profile
from .config import browser_profile_dir, project_root, runs_dir, state_dir
from .providers import ProviderInfo, default_registry
from .recovery.models import ContextThresholds
from .safety import SafetyPolicy

SETTINGS_FILE = "settings.json"


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # adapter selects the registered provider (M9): 'browser' drives a web LLM
    # through Playwright, 'openai_compatible' talks HTTP, 'scripted' replays a
    # plan. Changing provider is a settings change, never a code change.
    adapter: str = "browser"
    # name is the browser profile (the browser adapter) or the model label of
    # an HTTP adapter; profiles lists what backend/profiles ships.
    name: str = "mock"
    url: str = ""
    verified: bool = False
    notes: str = ""
    profiles: list[str] = Field(default_factory=list)
    # The HTTP adapter's model name. It lives here, next to the adapter, rather
    # than inside options, so the settings page can show the obvious field.
    model: str = ""
    # Adapter-specific options (base_url, plan, ...). Secret options are
    # stripped before the document is written.
    options: dict[str, str] = Field(default_factory=dict)
    # Read-only catalog derived from the provider registry, like the role list
    # is derived from the code.
    available: list[ProviderInfo] = Field(default_factory=list)


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile_dir: str = ""
    artifacts_dir: str = ""
    # The browser is headed by policy; this stays false and is shown so the
    # console can say why.
    headless_allowed: bool = False


class SafetySettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_root: str = ""
    extra_roots: list[str] = Field(default_factory=list)
    confirm_high_risk: bool = True
    sensitive_names: list[str] = Field(default_factory=list)


class ConfirmationSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # ask       - every high-risk call waits for a human (the default)
    # auto_once - the runtime answers "once" automatically (unattended runs)
    # deny      - the runtime always rejects
    #
    # "once" is accepted as an alias for "auto_once" and normalised, so a
    # client that used either spelling always reads back the canonical one.
    policy: str = Field(default="ask")
    ttl_seconds: int = Field(default=300, ge=1)

    @field_validator("policy")
    @classmethod
    def _known_policy(cls, value: str) -> str:
        normalised = {"once": "auto_once"}.get(value, value)
        if normalised not in ("ask", "auto_once", "deny"):
            raise ValueError("policy must be ask, auto_once or deny")
        return normalised


class ContextSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    soft_ratio: float = Field(default=0.7, gt=0, le=1)
    hard_ratio: float = Field(default=0.9, gt=0, le=1)
    soft_recent_turns: int = Field(default=2, ge=0)


class MultiAgentRoleInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    purpose: str
    allowed_tools: list[str] = Field(default_factory=list)
    max_steps: int = 0


class MultiAgentSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    max_rounds: int = Field(default=3, ge=1, le=20)
    stall_threshold: int = Field(default=2, ge=2, le=10)
    roles: list[MultiAgentRoleInfo] = Field(default_factory=list)


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    working_dir: str = ""
    safety: SafetySettings = Field(default_factory=SafetySettings)
    confirmation: ConfirmationSettings = Field(default_factory=ConfirmationSettings)
    context_thresholds: ContextSettings = Field(default_factory=ContextSettings)
    multi_agent: MultiAgentSettings = Field(default_factory=MultiAgentSettings)


def _role_info() -> list[MultiAgentRoleInfo]:
    from .agents.roles import DEFAULT_ROLES

    return [
        MultiAgentRoleInfo(
            name=role.name,
            purpose=role.purpose,
            allowed_tools=list(role.allowed_tools),
            max_steps=role.max_steps,
        )
        for role in DEFAULT_ROLES.values()
    ]


def provider_catalog() -> list[ProviderInfo]:
    """Every provider this deployment can run (M9)."""
    return default_registry().infos()


def default_settings() -> Settings:
    """The live defaults: read from the environment, not invented."""
    profiles = list_profiles()
    provider = ProviderSettings(profiles=profiles)
    if profiles:
        try:
            first = load_profile(profiles[0])
            provider = ProviderSettings(
                name=first.name,
                url=first.url,
                verified=first.verified,
                notes=first.notes,
                profiles=profiles,
            )
        except Exception:  # pragma: no cover - a broken profile must not break the page
            pass

    policy = SafetyPolicy(project_root=project_root())
    thresholds = ContextThresholds()

    provider.available = provider_catalog()

    return Settings(
        provider=provider,
        browser=BrowserSettings(
            profile_dir=str(browser_profile_dir()),
            artifacts_dir=str(runs_dir()),
            headless_allowed=False,
        ),
        working_dir=str(project_root()),
        safety=SafetySettings(
            project_root=str(project_root()),
            extra_roots=[str(root) for root in policy.extra_roots],
            confirm_high_risk=True,
            sensitive_names=sorted(policy.sensitive_names),
        ),
        confirmation=ConfirmationSettings(),
        context_thresholds=ContextSettings(
            soft_ratio=thresholds.soft_ratio,
            hard_ratio=thresholds.hard_ratio,
            soft_recent_turns=thresholds.soft_recent_turns,
        ),
        multi_agent=MultiAgentSettings(roles=_role_info()),
    )


def _public_options(payload: dict) -> dict:
    """Drop secret option values before the document is written."""
    stored = dict(payload.get("options") or {})
    adapter = payload.get("adapter") or "browser"
    try:
        info = default_registry().get(adapter).info
    except Exception:  # pragma: no cover - an unknown adapter keeps what it has
        return stored
    for option in info.options:
        if option.secret:
            stored.pop(option.name, None)
    return stored


class SettingsStore:
    """Persist the console's settings next to the other state."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else state_dir() / SETTINGS_FILE

    def load(self) -> Settings:
        """Current settings: defaults, with whatever the file overrides."""
        defaults = default_settings()
        if not self.path.exists():
            return defaults
        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return defaults
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            return defaults
        if not isinstance(stored, dict):
            return defaults
        # Merge so a new field appears with its default instead of vanishing.
        merged = defaults.model_dump(mode="json")
        for key, value in stored.items():
            if key == "multi_agent" and isinstance(value, dict):
                # roles are read-only (they come from the code)
                value = {k: v for k, v in value.items() if k != "roles"}
                merged["multi_agent"].update(value)
            elif key == "provider" and isinstance(value, dict):
                # the catalog is read-only too: it comes from the registry
                value = {k: v for k, v in value.items() if k != "available"}
                merged["provider"].update(value)
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        try:
            return Settings.model_validate(merged)
        except Exception:
            return defaults

    def save(self, settings: Settings) -> Settings:
        payload = settings.model_dump(mode="json")
        # roles always come from the code, never from the document
        payload["multi_agent"]["roles"] = [
            role.model_dump(mode="json") for role in _role_info()
        ]
        payload["provider"]["available"] = [
            info.model_dump(mode="json") for info in provider_catalog()
        ]
        # A secret option is never written to disk: it is read from the
        # environment when the provider is built.
        payload["provider"]["options"] = _public_options(payload["provider"])
        payload["browser"]["headless_allowed"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return Settings.model_validate(payload)
