"""Dependency wiring for the API layer."""

from __future__ import annotations

import threading
from typing import Any

from .context import SessionManager
from .storage import StateStore


_runtime = None
_model = None
_runtime_lock = threading.Lock()
_model_lock = threading.Lock()


def build_console_model() -> Any:
    """The ModelClient the console should use, chosen by the settings document.

    Provider selection goes through the M9 registry, so switching to an HTTP
    model (or a scripted one) is a settings change; the AgentLoop, the parser,
    the SafetyLayer and the Executor are the same either way.

    Options that the chosen adapter does not declare are ignored, because one
    settings document holds the options of every adapter (a base_url may sit
    there while the browser adapter is active). A misspelled option for the
    ACTIVE adapter is still rejected by the registry, which is where a silent
    typo would otherwise hide.
    """
    from .providers import default_registry
    from .settings import SettingsStore

    settings = SettingsStore().load()
    provider = default_registry().get(settings.provider.adapter or "browser")
    declared = {option.name for option in provider.info.options}
    supplied = {
        key: value
        for key, value in (settings.provider.options or {}).items()
        if value not in (None, "") and key in declared
    }
    if provider.info.name == "browser":
        supplied.setdefault("profile", settings.provider.name)
        if settings.browser.artifacts_dir:
            supplied.setdefault("artifacts_dir", settings.browser.artifacts_dir)
    elif provider.info.name == "openai_compatible" and settings.provider.model:
        supplied.setdefault("model", settings.provider.model)
    return provider.create(**supplied)


def get_console_model() -> Any:
    """The console's model, built once per process (a browser session is costly)."""
    global _model
    with _model_lock:
        if _model is None:
            _model = build_console_model()
        return _model


def get_agent_runtime():
    """The console's single agent runtime.

    One per process: it owns the running task, its event ring and its
    confirmation queue, all of which only make sense as singletons.
    """
    global _runtime
    if _runtime_lock is None:  # pragma: no cover - kept for older callers
        pass
    with _runtime_lock:
        if _runtime is None:
            from .runtime import AgentRuntime

            _runtime = AgentRuntime(model_factory=get_console_model)
        return _runtime


def reset_agent_runtime() -> None:
    """Drop the cached runtime and model (tests, and a provider change)."""
    global _runtime, _model
    with _runtime_lock:
        _runtime = None
    with _model_lock:
        _model = None


def get_session_manager() -> SessionManager:
    """Session manager for one request (paths resolved per call)."""
    return SessionManager()


def get_state_store() -> StateStore:
    """Build a store per request.

    Deliberately not cached: the state directory is resolved from the
    environment on every call, so tests (and any future reconfiguration)
    observe the current paths instead of a stale instance.
    """
    return StateStore()
