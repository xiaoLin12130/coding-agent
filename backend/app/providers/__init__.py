"""Provider adapters (M9).

The AgentLoop depends on a ModelClient protocol only. Every concrete way of
reaching a model lives here, behind a registry, so adding a provider is an
adapter plus a registration and nothing else.
"""

from __future__ import annotations

from .models import ProviderError, ProviderInfo, ProviderKind, ProviderOption
from .registry import (
    ProviderRegistry,
    RegisteredProvider,
    build_model,
    default_registry,
    register_provider,
)

__all__ = [
    "ProviderError",
    "ProviderInfo",
    "ProviderKind",
    "ProviderOption",
    "ProviderRegistry",
    "RegisteredProvider",
    "build_model",
    "default_registry",
    "register_provider",
]
