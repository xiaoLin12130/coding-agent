"""M9: the offline (scripted) provider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers import ProviderError, default_registry
from app.providers.scripted import read_plan


def test_a_plan_file_is_a_list_of_replies(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(["one", "two"]), encoding="utf-8")
    assert read_plan(plan) == ["one", "two"]


def test_a_plan_file_may_wrap_the_list(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"replies": ["one"]}), encoding="utf-8")
    assert read_plan(plan) == ["one"]


def test_a_structured_reply_is_serialised_back_to_json(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps([{"name": "read_file", "arguments": {"path": "a.txt"}}]), encoding="utf-8"
    )
    assert json.loads(read_plan(plan)[0])["name"] == "read_file"


def test_a_missing_plan_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ProviderError) as caught:
        read_plan(tmp_path / "nope.json")
    assert "no such plan file" in str(caught.value)


def test_a_broken_plan_file_is_reported(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderError) as caught:
        read_plan(plan)
    assert "not valid JSON" in str(caught.value)


def test_a_plan_that_is_neither_list_nor_wrapper_is_reported(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text('"just a string"', encoding="utf-8")
    with pytest.raises(ProviderError):
        read_plan(plan)


def test_the_model_hands_out_the_plan_in_order_and_then_stops(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(["one", "two"]), encoding="utf-8")
    model = default_registry().create("scripted", plan=str(plan), final_message="done")
    assert model.complete("a").text == "one"
    assert model.complete("b").text == "two"
    assert model.complete("c").text == "done"
    assert model.name == "scripted"


def test_inline_replies_need_no_file() -> None:
    model = default_registry().create("scripted", replies=["only"], label="eval")
    assert model.name == "eval"
    assert model.complete("x").text == "only"


def test_inline_replies_must_be_a_list() -> None:
    with pytest.raises(ProviderError):
        default_registry().create("scripted", replies="one")
