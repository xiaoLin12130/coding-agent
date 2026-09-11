"""M9: the evaluation command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.cli import main


def test_the_parser_suite_runs_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--suite", "parser", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "evaluation: PASS" in out
    assert "exact match 100.0%" in out
    assert (tmp_path / "out" / "report.md").exists()


def test_json_output_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--suite", "parser", "--out", str(tmp_path / "out"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parser"]["exact_match_rate"] == 1.0


def test_an_impossible_threshold_fails_with_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--suite", "parser", "--out", str(tmp_path / "out"), "--parser-rate", "1.5"])
    assert code == 1
    assert "THRESHOLD parser.exact_match_rate" in capsys.readouterr().out


def test_stdout_output_writes_no_files(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--suite", "parser", "--out", "-"]) == 0
    assert "Parser golden set" in capsys.readouterr().out


def test_the_agent_suite_can_be_run_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--suite", "agent", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "tool_selection" in out
    assert "context_switching" in out
