"""Provider registry: the one seam a new provider plugs into (M9).

Adding a provider means writing an adapter and registering it here. Nothing in
app/agents changes, which is exactly what milestones/M9.md requires
(a new provider must not modify the AgentLoop core).

The registry is deliberately strict about option names: a misspelled option
raises instead of being ignored, so a provider is never silently built with
settings the caller never supplied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable

from .models import ProviderError, ProviderInfo

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.llm import ModelClient

# A factory receives the validated options and returns a ModelClient.
ProviderFactory = Callable[..., "ModelClient"]


class RegisteredProvider:
    """A provider description plus the factory that builds its model."""

    def __init__(self, info: ProviderInfo, factory: ProviderFactory) -> None:
        self.info = info
        self._factory = factory

    # -- options -----------------------------------------------------------

    def validate(self, options: dict[str, Any]) -> dict[str, Any]:
        """Check option names and fill in declared defaults."""
        known = {option.name for option in self.info.options}
        unknown = sorted(set(options) - known)
        if unknown:
            raise ProviderError(
                "provider '" + self.info.name + "' does not accept option(s): "
                + ", ".join(unknown)
                + ((" (known: " + ", ".join(sorted(known)) + ")") if known else " (it takes none)")
            )
        merged = {
            option.name: option.default
            for option in self.info.options
            if option.default != ""
        }
        merged.update({key: value for key, value in options.items() if value is not None})
        missing = [
            option.name
            for option in self.info.options
            if option.required and not merged.get(option.name)
        ]
        if missing:
            raise ProviderError(
                "provider '" + self.info.name + "' is missing required option(s): "
                + ", ".join(missing)
            )
        return merged

    def create(self, **options: Any) -> "ModelClient":
        return self._factory(**self.validate(options))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<RegisteredProvider " + self.info.name + " (" + self.info.kind + ")>"


class ProviderRegistry:
    """The set of providers a deployment can choose from."""

    def __init__(self, providers: Iterable[RegisteredProvider] | None = None) -> None:
        self._providers: dict[str, RegisteredProvider] = {}
        for provider in providers or ():
            self.register(provider.info, provider._factory)

    # -- registration ------------------------------------------------------

    def register(
        self,
        info: ProviderInfo,
        factory: ProviderFactory | None = None,
        *,
        replace: bool = False,
    ) -> Any:
        """Register a provider, directly or as a decorator.

        Re-registering a name without replace=True raises, so two adapters
        cannot fight over one name.
        """
        if info.name in self._providers and not replace:
            raise ProviderError("provider '" + info.name + "' is already registered")

        def _install(function: ProviderFactory) -> ProviderFactory:
            self._providers[info.name] = RegisteredProvider(info, function)
            return function

        if factory is None:
            return _install
        _install(factory)
        return self._providers[info.name]

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    # -- lookup ------------------------------------------------------------

    def names(self) -> list[str]:
        return sorted(self._providers)

    def infos(self) -> list[ProviderInfo]:
        return [self._providers[name].info for name in self.names()]

    def get(self, name: str) -> RegisteredProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ProviderError(
                "unknown provider '" + name + "'; registered: "
                + (", ".join(self.names()) or "(none)")
            )
        return provider

    def create(self, name: str, **options: Any) -> "ModelClient":
        return self.get(name).create(**options)

    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def __len__(self) -> int:
        return len(self._providers)


_DEFAULT: ProviderRegistry | None = None


def default_registry() -> ProviderRegistry:
    """The deployment's registry, built with every shipped provider."""
    global _DEFAULT
    if _DEFAULT is None:
        from .browser import register as register_browser
        from .openai_compatible import register as register_openai
        from .scripted import register as register_scripted

        registry = ProviderRegistry()
        register_browser(registry)
        register_scripted(registry)
        register_openai(registry)
        _DEFAULT = registry
    return _DEFAULT


def register_provider(info: ProviderInfo, factory: ProviderFactory | None = None) -> Any:
    """Register an extra provider on the default registry (extension seam)."""
    return default_registry().register(info, factory)


def build_model(adapter: str = "browser", **options: Any) -> "ModelClient":
    """Build a ModelClient for a named provider.

    This is the only call the rest of the system makes, so switching provider
    is a configuration change rather than a code change.
    """
    return default_registry().create(adapter, **options)
