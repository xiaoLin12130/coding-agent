"""M9: the provider registry is the seam, and it is strict about it."""

from __future__ import annotations

import inspect

import pytest

from app.agents import llm
from app.agents.llm import ScriptedModel
from app.providers import (
    ProviderError,
    ProviderInfo,
    ProviderOption,
    ProviderRegistry,
    build_model,
    default_registry,
)


def test_the_shipped_providers_are_registered() -> None:
    registry = default_registry()
    assert registry.names() == ["browser", "openai_compatible", "scripted"]
    kinds = {info.name: info.kind for info in registry.infos()}
    assert kinds == {"browser": "browser", "openai_compatible": "api", "scripted": "offline"}


def test_a_provider_says_what_it_needs() -> None:
    infos = {info.name: info for info in default_registry().infos()}
    assert infos["browser"].requires_login is True
    assert infos["scripted"].requires_network is False
    assert infos["openai_compatible"].requires_network is True
    assert infos["openai_compatible"].option("api_key").secret is True


def test_the_catalog_serialises_for_the_settings_page() -> None:
    payload = [info.model_dump(mode="json") for info in default_registry().infos()]
    assert all("kind" in item and "options" in item for item in payload)


def test_registering_the_same_name_twice_is_refused() -> None:
    registry = ProviderRegistry()
    info = ProviderInfo(name="echo", kind="offline", label="Echo")
    registry.register(info, lambda **_: ScriptedModel([]))
    with pytest.raises(ProviderError):
        registry.register(info, lambda **_: ScriptedModel([]))


def test_replace_allows_a_new_factory() -> None:
    registry = ProviderRegistry()
    info = ProviderInfo(name="echo", kind="offline", label="Echo")
    registry.register(info, lambda **_: ScriptedModel(["first"]))
    registry.register(info, lambda **_: ScriptedModel(["second"]), replace=True)
    assert registry.create("echo").complete("hi").text == "second"


def test_registration_works_as_a_decorator() -> None:
    registry = ProviderRegistry()
    info = ProviderInfo(name="echo", kind="offline", label="Echo")

    @registry.register(info)
    def factory(**_options):
        return ScriptedModel(["hi"])

    assert registry.create("echo").complete("x").text == "hi"


def test_an_unknown_provider_lists_what_exists() -> None:
    with pytest.raises(ProviderError) as caught:
        default_registry().get("nope")
    message = str(caught.value)
    assert "nope" in message
    assert "scripted" in message


def test_an_unknown_option_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ProviderError) as caught:
        default_registry().create("scripted", plna="plan.json")
    assert "plna" in str(caught.value)


def test_a_required_option_must_be_supplied() -> None:
    with pytest.raises(ProviderError) as caught:
        default_registry().create("openai_compatible", model="m")
    assert "base_url" in str(caught.value)


def test_declared_defaults_are_filled_in() -> None:
    provider = default_registry().get("openai_compatible")
    merged = provider.validate({"base_url": "http://127.0.0.1:1/v1", "model": "m"})
    assert merged["api_key_env"] == "OPENAI_API_KEY"
    assert merged["timeout_s"] == "120"


def test_the_one_shipped_offline_provider_builds_a_model() -> None:
    model = build_model("scripted", replies=["hello"])
    assert isinstance(model, ScriptedModel)
    assert model.complete("prompt").text == "hello"


def test_an_extra_provider_can_be_registered_without_touching_the_loop() -> None:
    """The milestone's rule, checked structurally: the loop never sees a registry."""
    registry = ProviderRegistry()
    info = ProviderInfo(
        name="unit-test",
        kind="offline",
        label="Unit test",
        options=[ProviderOption(name="greeting", default="hi")],
    )
    registry.register(info, lambda greeting="hi", **_: ScriptedModel([greeting]))

    assert registry.create("unit-test", greeting="hello").complete("x").text == "hello"
    assert registry.create("unit-test").complete("x").text == "hi"

    loop_source = inspect.getsource(llm)
    assert "providers" not in loop_source
    from app.agents import loop

    source = inspect.getsource(loop)
    assert "providers" not in source
    assert "ProviderRegistry" not in source
