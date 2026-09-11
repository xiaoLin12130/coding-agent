"""Agent CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents import cli


def _args(tmp_path: Path, *rest: str, json_output: bool = False) -> list[str]:
    """Global flags first, then the subcommand (argparse requires that order)."""
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    global_flags = [
        "--working-dir",
        str(project),
        "--sessions-dir",
        str(project / "state" / "sessions"),
        "--checkpoints-dir",
        str(project / "state" / "checkpoints"),
        "--log",
        str(project / "runs" / "tool-calls.jsonl"),
        "--quiet",
    ]
    if json_output:
        global_flags.append("--json")
    return global_flags + list(rest)


def _script(tmp_path: Path, replies: list[str]) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"replies": replies}), encoding="utf-8")
    return path


def test_run_command_completes_a_task(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("content", encoding="utf-8")
    script = _script(
        tmp_path,
        [json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}}), "all done"],
    )

    exit_code = cli.main(_args(tmp_path, "run", "--task", "read it", "--script", str(script)))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status    : completed" in out
    assert "read_file" in out


def test_run_command_reports_a_non_completed_run(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        _args(tmp_path, "run", "--task", "t", "--max-steps", "1", "--script", str(_script(tmp_path, [])))
    )

    assert exit_code == 0, "an empty script still yields a final answer"


def test_run_command_json_output(tmp_path: Path, capsys) -> None:
    cli.main(
        _args(
            tmp_path,
            "run",
            "--task",
            "t",
            "--script",
            str(_script(tmp_path, ["done"])),
            json_output=True,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["run_id"]


def test_run_command_writes_a_checkpoint(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("x", encoding="utf-8")
    script = _script(
        tmp_path,
        [json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}}), "done"],
    )

    cli.main(_args(tmp_path, "run", "--task", "t", "--script", str(script), "--run-id", "run-cli"))

    stored = (project / "state" / "checkpoints" / "run-cli.json")
    assert stored.exists()
    assert json.loads(stored.read_text(encoding="utf-8"))["task"] == "t"


def test_checkpoints_command_lists_runs(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("x", encoding="utf-8")
    script = _script(
        tmp_path,
        [json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}}), "done"],
    )
    cli.main(_args(tmp_path, "run", "--task", "listed task", "--script", str(script), "--run-id", "abc"))

    capsys.readouterr()
    assert cli.main(_args(tmp_path, "checkpoints")) == 0
    assert "abc" in capsys.readouterr().out


def test_checkpoints_command_on_an_empty_store(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "checkpoints")) == 0
    assert "no checkpoints" in capsys.readouterr().out


def test_resume_command_continues_a_run(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("x", encoding="utf-8")
    first = _script(
        tmp_path,
        [json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}})],
    )
    # one step only, so the run stops with a checkpoint
    cli.main(
        _args(
            tmp_path, "run", "--task", "resume me", "--script", str(first),
            "--run-id", "res", "--max-steps", "1",
        )
    )
    capsys.readouterr()

    exit_code = cli.main(_args(tmp_path, "resume", "--run-id", "res"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status    : completed" in out


def test_resume_without_a_checkpoint_fails(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(_args(tmp_path, "resume", "--run-id", "missing"))

    assert exit_code == 2
    assert "no checkpoint" in capsys.readouterr().err


def test_a_script_file_can_be_a_plain_list(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text(json.dumps(["reply one"]), encoding="utf-8")

    exit_code = cli.main(_args(tmp_path, "run", "--task", "t", "--script", str(path)))

    assert exit_code == 0


def test_a_malformed_script_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps("not a list"), encoding="utf-8")

    try:
        cli.main(_args(tmp_path, "run", "--task", "t", "--script", str(path)))
    except SystemExit as exc:
        assert "must be a list" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit")


def test_the_cli_does_not_bypass_the_executor(tmp_path: Path) -> None:
    """A blocked call stays blocked when driven from the CLI."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    script = _script(
        tmp_path,
        [
            json.dumps({"name": "read_file", "arguments": {"path": str(outside)}}),
            "cannot read that",
        ],
    )

    exit_code = cli.main(
        _args(
            tmp_path,
            "run",
            "--task",
            "read outside",
            "--script",
            str(script),
            json_output=True,
        )
    )

    assert exit_code == 1, "a blocked run is not a completed one"
