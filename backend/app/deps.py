"""Dependency wiring for the API layer."""

from __future__ import annotations

from .storage import StateStore


def get_state_store() -> StateStore:
    """Build a store per request.

    Deliberately not cached: the state directory is resolved from the
    environment on every call, so tests (and any future reconfiguration)
    observe the current paths instead of a stale instance.
    """
    return StateStore()
