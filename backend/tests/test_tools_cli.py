"""Tool CLI smoke tests (same Executor path as the model will use)."""

from __future__ import annotations

import json
from pathlib import Path

from app.tools import cli


def _args(tmp_path: Path, *rest: str) -> list[str]:
    return [
        "--working-dir",
        str(tmp_path),
        "--log",
        str(tmp_path / "tool-calls.jsonl"),
        *rest,
    ]


def test_list_command_shows_every_tool(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "list")) == 0
    out = capsys.readouterr().out

    assert "9 tool(s)" in out
    for name in (
        "list_dir",
        "read_file",
        "write_file",
        "apply_patch",
        "search",
        "run_shell",
        "memory_propose",
        "update_project_state",
        "ask_user",
    ):
        assert name in out


def test_list_command_json_is_machine_readable(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "list", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert len(payload) == 9
    assert {entry["name"] for entry in payload} >= {"read_file", "run_shell"}


def test_schema_command_prints_one_schema(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "schema", "read_file")) == 0
    schema = json.loads(capsys.readouterr().out)

    assert schema["type"] == "object"
    assert "path" in schema["properties"]


def test_run_command_executes_through_the_executor(tmp_path: Path, capsys) -> None:
    (tmp_path / "a.txt").write_text("cli content", encoding="utf-8")

    exit_code = cli.main(
        _args(tmp_path, "run", "read_file", "--args", '{"path": "a.txt"}')
    )

    assert exit_code == 0
    assert "cli content" in capsys.readouterr().out


def test_run_command_writes_the_log(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    cli.main(_args(tmp_path, "run", "read_file", "--args", '{"path": "a.txt"}'))

    lines = (tmp_path / "tool-calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "read_file"


def test_run_command_requires_confirmation_for_high_risk(
    tmp_path: Path, capsys
) -> None:
    exit_code = cli.main(
        _args(tmp_path, "run", "run_shell", "--args", '{"command": "echo hi"}')
    )

    assert exit_code == 1
    assert "confirmation_required" in capsys.readouterr().out


def test_run_command_runs_when_confirmed(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        _args(
            tmp_path,
            "run",
            "run_shell",
            "--args",
            '{"command": "echo confirmed"}',
            "--confirm",
        )
    )

    assert exit_code == 0
    assert "confirmed" in capsys.readouterr().out


def test_run_command_rejects_bad_json_arguments(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(_args(tmp_path, "run", "read_file", "--args", "{oops"))

    assert exit_code == 2
    assert "must be JSON" in capsys.readouterr().err


def test_run_command_rejects_a_json_array(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(_args(tmp_path, "run", "read_file", "--args", "[1, 2]"))

    assert exit_code == 2
    assert "JSON object" in capsys.readouterr().err


def test_run_command_reports_an_unknown_tool(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(_args(tmp_path, "run", "not_a_tool"))

    assert exit_code == 1
    assert "unknown_tool" in capsys.readouterr().out


def test_run_command_json_mode(tmp_path: Path, capsys) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    cli.main(_args(tmp_path, "run", "read_file", "--args", '{"path": "a.txt"}', "--json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["name"] == "read_file"
    assert payload["risk"] == "low"


def test_parse_command_accepts_json5(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        _args(tmp_path, "parse", "--text", "{name: 'list_dir', args: {}}")
    )

    assert exit_code == 0
    assert "list_dir" in capsys.readouterr().out


def test_parse_command_reports_issues_and_exit_code(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        _args(tmp_path, "parse", "--text", '{"name": "rm_rf", "arguments": {}}')
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "unknown_tool" in out
    assert "fix:" in out


def test_parse_command_checks_tool_names_unless_disabled(
    tmp_path: Path, capsys
) -> None:
    cli.main(_args(tmp_path, "parse", "--text", '{"name": "invented", "arguments": {}}'))
    assert "unknown_tool" in capsys.readouterr().out

    exit_code = cli.main(
        _args(tmp_path, "parse", "--text", '{"name": "invented", "arguments": {}}', "--any-tool")
    )
    assert exit_code == 0
    assert "invented" in capsys.readouterr().out
