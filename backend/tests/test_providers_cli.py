"""M9: the provider command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers.cli import main


def test_list_shows_every_provider(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "browser" in out
    assert "openai_compatible" in out
    assert "scripted" in out
    assert "offline" in out


def test_list_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {item["name"] for item in payload} == {"browser", "openai_compatible", "scripted"}


def test_show_explains_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", "openai_compatible"]) == 0
    out = capsys.readouterr().out
    assert "base_url" in out
    assert "required" in out
    assert "secret" in out


def test_show_reports_an_unknown_provider(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", "nope"]) == 2
    assert "unknown provider" in capsys.readouterr().err


def test_check_builds_a_provider_without_asking_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(["hi"]), encoding="utf-8")
    assert main(["check", "scripted", "--option", "plan=" + str(plan)]) == 0
    out = capsys.readouterr().out
    assert "not requested" in out


def test_check_can_ask_the_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(["hello from the plan"]), encoding="utf-8")
    assert main(["check", "scripted", "--option", "plan=" + str(plan), "--prompt", "hi"]) == 0
    assert "hello from the plan" in capsys.readouterr().out


def test_check_reports_a_missing_required_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "openai_compatible", "--option", "model=m"]) == 2
    assert "base_url" in capsys.readouterr().err


def test_check_reports_a_typo_in_an_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "scripted", "--option", "plna=x.json"]) == 2
    assert "plna" in capsys.readouterr().err


def test_a_malformed_option_pair_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["check", "scripted", "--option", "plan"])
