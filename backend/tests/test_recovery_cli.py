"""Recovery CLI tests (M6)."""

from __future__ import annotations

import json
from pathlib import Path

from app.recovery import cli


def _args(tmp_path: Path, *rest: str, json_output: bool = False) -> list[str]:
    flags = [
        "--sessions-dir",
        str(tmp_path / "state" / "sessions"),
        "--checkpoints-dir",
        str(tmp_path / "state" / "checkpoints"),
    ]
    if json_output:
        flags.append("--json")
    return flags + list(rest)


def test_status_reports_the_recoverable_state(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "status")) == 0
    out = capsys.readouterr().out

    assert "active session" in out
    assert "memory entries" in out
    assert "latest run" in out


def test_status_json_is_machine_readable(tmp_path: Path, capsys) -> None:
    cli.main(_args(tmp_path, "status", json_output=True))

    payload = json.loads(capsys.readouterr().out)
    assert "active_session_id" in payload
    assert "archived_session_ids" in payload


def test_pressure_reports_a_level(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "pressure", "--task", "finish M6")) == 0
    out = capsys.readouterr().out

    assert "OK" in out or "SOFT" in out or "HARD" in out
    assert "chars" in out


def test_runs_is_empty_without_checkpoints(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "runs")) == 0
    assert "no unfinished runs" in capsys.readouterr().out


def test_rotate_runs_the_sequence(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "state").mkdir(exist_ok=True)

    exit_code = cli.main(_args(tmp_path, "rotate", "--reason", "manual"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "archived session" in out
    assert "opened session" in out
    assert "injected project state" in out


def test_resume_without_a_checkpoint_fails(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(_args(tmp_path, "resume", "--run-id", "nope"))

    assert exit_code == 1
    assert "no checkpoint" in capsys.readouterr().out


def test_resume_continues_a_stopped_run(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("content", encoding="utf-8")
    script = tmp_path / "plan.json"
    script.write_text(
        json.dumps({"replies": [json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}})]}),
        encoding="utf-8",
    )

    # stop a run after one step
    from app.agents import cli as agent_cli

    agent_cli.main(
        [
            "--working-dir", str(project),
            "--sessions-dir", str(tmp_path / "state" / "sessions"),
            "--checkpoints-dir", str(tmp_path / "state" / "checkpoints"),
            "--log", str(project / "runs" / "log.jsonl"),
            "--quiet",
            "run", "--task", "finish it", "--script", str(script),
            "--run-id", "cli-run", "--max-steps", "1",
        ]
    )
    capsys.readouterr()

    exit_code = cli.main(
        _args(
            tmp_path,
            "resume",
            "--run-id",
            "cli-run",
            "--working-dir",
            str(project),
            "--log",
            str(project / "runs" / "log.jsonl"),
        )
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "found checkpoint" in out
    assert "status    : completed" in out
