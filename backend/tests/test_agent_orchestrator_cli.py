"""Orchestration CLI tests (M7)."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents import cli


def _args(tmp_path: Path, *rest: str, json_output: bool = False) -> list[str]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    flags = [
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
        flags.append("--json")
    return flags + list(rest)


def tool(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


def _write_script(tmp_path: Path, replies: dict[str, list[str]]) -> Path:
    """A per-role script: each role gets its own reply list."""
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(replies), encoding="utf-8")
    return path


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "tests").mkdir(exist_ok=True)
    (project / "src" / "calc.py").write_text(
        "def add(a, b):" + chr(10) + "    return a - b" + chr(10), encoding="utf-8"
    )
    (project / "tests" / "check.py").write_text("print('1 passed')", encoding="utf-8")
    return project


def test_roles_command_lists_the_six_roles(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "roles")) == 0
    out = capsys.readouterr().out

    assert "6 role(s)" in out
    for name in (
        "planner",
        "coder",
        "reviewer",
        "memory_curator",
        "state_keeper",
        "safety_guard",
    ):
        assert name in out


def test_roles_command_json_is_machine_readable(tmp_path: Path, capsys) -> None:
    cli.main(_args(tmp_path, "roles", json_output=True))
    payload = json.loads(capsys.readouterr().out)

    assert len(payload) == 6
    planner = next(entry for entry in payload if entry["name"] == "planner")
    assert "write_file" not in planner["allowed_tools"]


def test_orchestrate_runs_the_collaboration(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    script = _write_script(
        tmp_path,
        {
            "planner": ["1. read src/calc.py" + chr(10) + "2. patch it"],
            "safety_guard": ["VERDICT: SAFE"],
            "coder": [
                tool(
                    "apply_patch",
                    path="src/calc.py",
                    hunks=[{"old": "return a - b", "new": "return a + b"}],
                ),
                "patched add()",
            ],
            "reviewer": ["VERDICT: APPROVED"],
            "state_keeper": ["recorded"],
            "memory_curator": ["nothing to remember"],
        },
    )

    exit_code = cli.main(
        _args(
            tmp_path,
            "orchestrate",
            "--task",
            "fix add()",
            "--script",
            str(script),
            "--max-rounds",
            "1",
            "--confirm",
            "once",
        )
    )

    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "status    : completed" in out
    assert "rounds    : 1 of 1" in out
    assert "coder" in out
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8").endswith(
        "return a + b" + chr(10)
    )


def test_orchestrate_json_output(tmp_path: Path, capsys) -> None:
    _project(tmp_path)
    script = _write_script(
        tmp_path,
        {
            "planner": ["a plan"],
            "safety_guard": ["VERDICT: SAFE"],
            "coder": ["done"],
            "reviewer": ["VERDICT: APPROVED"],
            "state_keeper": ["ok"],
            "memory_curator": ["none"],
        },
    )

    cli.main(
        _args(
            tmp_path,
            "orchestrate",
            "--task",
            "t",
            "--script",
            str(script),
            "--max-rounds",
            "1",
            "--confirm",
            "once",
            json_output=True,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["plan"] == "a plan"
    assert payload["round_count"] == 1


def test_orchestrate_reports_a_blocked_plan(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    script = _write_script(
        tmp_path,
        {
            "planner": ["1. delete everything"],
            "safety_guard": ["VERDICT: BLOCKED" + chr(10) + "ISSUE: the plan is destructive"],
        },
    )

    exit_code = cli.main(
        _args(
            tmp_path,
            "orchestrate",
            "--task",
            "t",
            "--script",
            str(script),
            "--confirm",
            "once",
        )
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "status    : blocked" in out
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8").endswith(
        "return a - b" + chr(10)
    ), "a blocked plan must not touch the project"


def test_orchestrate_without_confirm_refuses_high_risk_calls(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    script = _write_script(
        tmp_path,
        {
            "planner": ["plan"],
            "safety_guard": ["VERDICT: SAFE"],
            "coder": [
                tool("run_shell", command="echo hi"),
                tool("run_shell", command="echo hi"),
                "could not run it",
            ],
            "reviewer": ["VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: the command never ran"],
            "state_keeper": ["recorded"],
            "memory_curator": ["none"],
        },
    )

    exit_code = cli.main(
        _args(
            tmp_path,
            "orchestrate",
            "--task",
            "t",
            "--script",
            str(script),
            "--max-rounds",
            "1",
            "--no-confirm",
        )
    )

    out = capsys.readouterr().out
    assert exit_code == 1, "an unapproved high-risk call must not end in success"
    assert "completed" not in out.split("status")[-1][:20]
