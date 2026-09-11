"""M9: the HTTP (OpenAI-compatible) provider.

Every test runs against an injected httpx transport, so the suite never opens a
network connection. The adapter is exercised through the same ModelClient
contract the AgentLoop uses.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.llm import ModelClientError
from app.providers import ProviderError, default_registry
from app.providers.openai_compatible import HttpChatModel


def make_model(handler, **kwargs) -> HttpChatModel:
    return HttpChatModel(
        base_url=kwargs.pop("base_url", "http://model.test/v1"),
        model=kwargs.pop("model", "test-model"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def answering(text: str, captured: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
        )

    return handler


def test_a_reply_becomes_a_model_reply() -> None:
    model = make_model(answering("hello"))
    reply = model.complete("hi")
    assert reply.text == "hello"
    assert reply.source == "model"
    assert reply.meta["model"] == "test-model"


def test_the_request_carries_the_system_prompt_then_the_prompt() -> None:
    captured: dict = {}
    model = make_model(answering("ok", captured))
    model.complete("do the thing", system="be careful")
    assert captured["url"] == "http://model.test/v1/chat/completions"
    assert captured["body"]["model"] == "test-model"
    assert [message["role"] for message in captured["body"]["messages"]] == ["system", "user"]
    assert captured["body"]["messages"][1]["content"] == "do the thing"


def test_temperature_is_omitted_unless_configured() -> None:
    captured: dict = {}
    make_model(answering("ok", captured)).complete("x")
    assert "temperature" not in captured["body"]

    captured.clear()
    make_model(answering("ok", captured), temperature=0.2).complete("x")
    assert captured["body"]["temperature"] == 0.2


def test_the_api_key_becomes_a_bearer_header() -> None:
    captured: dict = {}
    make_model(answering("ok", captured), api_key="secret-key").complete("x")
    assert captured["headers"]["authorization"] == "Bearer secret-key"


def test_the_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_MODEL_KEY", "from-env")
    model = default_registry().create(
        "openai_compatible",
        base_url="http://model.test/v1",
        model="m",
        api_key_env="MY_MODEL_KEY",
    )
    assert model.api_key == "from-env"
    model.close()


def test_the_key_is_never_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = default_registry().create(
        "openai_compatible", base_url="http://model.test/v1", model="m"
    )
    assert model.api_key == ""
    model.close()


def test_a_content_part_list_is_joined() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}
                ]
            },
        )

    assert make_model(handler).complete("x").text == "ab"


def test_the_legacy_text_field_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"text": "legacy"}]})

    assert make_model(handler).complete("x").text == "legacy"


def test_an_error_status_is_a_model_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ModelClientError) as caught:
        make_model(handler).complete("x")
    assert "500" in str(caught.value)


def test_a_transport_failure_is_a_model_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ModelClientError) as caught:
        make_model(handler).complete("x")
    assert "could not be reached" in str(caught.value)


def test_a_non_json_answer_is_a_model_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(ModelClientError):
        make_model(handler).complete("x")


def test_an_empty_answer_is_a_model_error() -> None:
    with pytest.raises(ModelClientError):
        make_model(answering("   ")).complete("x")


def test_an_answer_without_choices_is_a_model_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "x"})

    with pytest.raises(ModelClientError):
        make_model(handler).complete("x")


def test_a_trailing_slash_in_the_base_url_is_tolerated() -> None:
    captured: dict = {}
    make_model(answering("ok", captured), base_url="http://model.test/v1/").complete("x")
    assert captured["url"] == "http://model.test/v1/chat/completions"


def test_an_empty_base_url_or_model_is_refused() -> None:
    with pytest.raises(ProviderError):
        HttpChatModel(base_url="  ", model="m")
    with pytest.raises(ProviderError):
        HttpChatModel(base_url="http://model.test/v1", model=" ")


def test_a_non_numeric_timeout_is_refused() -> None:
    with pytest.raises(ProviderError):
        default_registry().create(
            "openai_compatible", base_url="http://x/v1", model="m", timeout_s="soon"
        )
