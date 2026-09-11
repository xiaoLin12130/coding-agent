"""Model client tests."""

from __future__ import annotations

import pytest

from app.agents import (
    BrowserModel,
    CallableModel,
    ModelClient,
    ModelClientError,
    ScriptedModel,
)


def test_scripted_model_returns_replies_in_order() -> None:
    model = ScriptedModel(["one", "two"])

    assert model.complete("p").text == "one"
    assert model.complete("p").text == "two"


def test_scripted_model_falls_back_to_the_final_message() -> None:
    model = ScriptedModel(["only"], final_message="all done")

    assert model.complete("p").text == "only"
    assert model.complete("p").text == "all done"
    assert model.exhausted_replies == 1


def test_scripted_model_records_the_prompts_it_saw() -> None:
    model = ScriptedModel(["x"])
    model.complete("first prompt")

    assert model.calls == ["first prompt"]


def test_scripted_model_snapshot_and_restore() -> None:
    model = ScriptedModel(["one", "two", "three"])
    model.complete("p")
    state = model.snapshot()

    resumed = ScriptedModel(["one", "two", "three"])
    resumed.restore(state)

    assert resumed.complete("p").text == "two"
    assert resumed.index == 2


def test_callable_model_wraps_a_function() -> None:
    model = CallableModel(lambda prompt, system: "echo:" + prompt)

    assert model.complete("hi").text == "echo:hi"


def test_models_satisfy_the_protocol() -> None:
    assert isinstance(ScriptedModel([]), ModelClient)
    assert isinstance(CallableModel(lambda p, s: ""), ModelClient)
    assert isinstance(BrowserModel(provider=None), ModelClient)


# --- browser-backed model -------------------------------------------------


class FakeReply:
    def __init__(self, text: str) -> None:
        self.text = text
        self.duration_ms = 12
        self.completed = True
        self.timed_out = False
        self.source = "network"
        self.artifacts = type("A", (), {"run_dir": "runs/x"})()


class FakeProvider:
    def __init__(self, replies=None) -> None:
        self.replies = list(replies or ["hello from the page"])
        self.prompts: list[str] = []

    def ask(self, prompt: str):
        self.prompts.append(prompt)
        return FakeReply(self.replies.pop(0) if self.replies else "")


def test_browser_model_adapts_a_provider_reply() -> None:
    provider = FakeProvider()
    model = BrowserModel(provider)

    reply = model.complete("do the thing", system="be brief")

    assert reply.text == "hello from the page"
    assert reply.source == "model"
    assert reply.duration_ms == 12
    assert reply.meta["capture_source"] == "network"
    assert "do the thing" in provider.prompts[0]
    assert "be brief" in provider.prompts[0]


def test_browser_model_reports_an_empty_reply_as_an_error() -> None:
    model = BrowserModel(FakeProvider(replies=[""]))

    with pytest.raises(ModelClientError):
        model.complete("p")


def test_browser_model_wraps_provider_failures() -> None:
    class Broken:
        def ask(self, prompt):
            raise RuntimeError("page crashed")

    with pytest.raises(ModelClientError) as excinfo:
        BrowserModel(Broken()).complete("p")

    assert "page crashed" in str(excinfo.value)


def test_browser_model_keeps_the_last_reply_for_the_log() -> None:
    model = BrowserModel(FakeProvider())
    model.complete("p")

    assert model.last_reply is not None
