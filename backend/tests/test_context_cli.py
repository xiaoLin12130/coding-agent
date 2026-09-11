"""Context CLI smoke tests (no model, no network)."""

from __future__ import annotations

import json
from pathlib import Path

from app.context import cli


def _args(tmp_path: Path, command: str, *rest: str) -> list[str]:
    """Build argv with the command first, then its flags (as documented)."""
    return [command, "--sessions-dir", str(tmp_path / "sessions"), *rest]


def test_sessions_command_reports_the_active_session(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "sessions", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["active_session_id"]
    assert payload["sessions"]


def test_resume_command_describes_what_a_restart_recovers(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.config import ENV_STATE_DIR
    from app.context import SessionManager
    from app.models import ProjectState
    from app.storage import StateStore

    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path))
    manager = SessionManager(tmp_path / "sessions")
    manager.start(session_id="resume-me")
    manager.record("user", "hello from before the restart")
    manager.save_project_state(
        ProjectState(current_milestone="M2", current_task="carry on")
    )

    assert cli.main(_args(tmp_path, "resume", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["session"]["id"] == "resume-me"
    assert payload["session"]["message_count"] == 1
    assert payload["project_state"]["current_milestone"] == "M2"
    assert "project_state" in payload["context"]["sections"]
    assert "transcript" in payload["context"]["sections"]


def test_context_command_reports_sections_and_budget(tmp_path: Path, capsys) -> None:
    assert cli.main(_args(tmp_path, "context", "--task", "do the thing", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["budget_chars"] > 0
    names = [s["name"] for s in payload["sections"]]
    assert names[0] == "system"
    assert "task" in names


def test_context_command_renders_and_flags_truncation(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        _args(tmp_path, "context", "--task", "t" * 5000, "--budget", "800", "--render")
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "rendered" in out


def test_transcript_command_shows_entries(tmp_path: Path, capsys) -> None:
    from app.context import SessionManager

    manager = SessionManager(tmp_path / "sessions")
    manager.start()
    manager.record("user", "first message")

    assert cli.main(_args(tmp_path, "transcript")) == 0
    out = capsys.readouterr().out
    assert "first message" in out


def test_rotate_command_archives_and_continues(tmp_path: Path, capsys) -> None:
    from app.context import SessionManager

    manager = SessionManager(tmp_path / "sessions")
    manager.start()
    manager.record("user", "old turn")
    manager.record("assistant", "old reply")
    manager.record("user", "new turn")
    old_id = manager.current_session_id()

    assert cli.main(_args(tmp_path, "rotate", "--reason", "manual", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["archived_session_id"] == old_id
    assert payload["new_session_id"] != old_id
    assert payload["reason"] == "manual"


def test_memory_command_lists_entries(tmp_path: Path, monkeypatch, capsys) -> None:
    from app.config import ENV_STATE_DIR
    from app.context import MemoryStore
    from app.context.models import MemoryProposal

    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path))
    MemoryStore().propose(MemoryProposal(key="k", value="visible fact"))

    assert cli.main(_args(tmp_path, "memory", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [e["key"] for e in payload] == ["k"]


def test_propose_command_reports_the_decision(tmp_path: Path, monkeypatch, capsys) -> None:
    from app.config import ENV_STATE_DIR

    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path))

    assert cli.main(_args(tmp_path, "propose", "--key", "a", "--value", "b")) == 0
    assert "accepted" in capsys.readouterr().out


def test_propose_command_rejects_a_secret_with_exit_code_2(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.config import ENV_STATE_DIR

    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path))

    exit_code = cli.main(
        _args(tmp_path, "propose", "--key", "leak", "--value", "password: hunter2hunter2")
    )

    assert exit_code == 2
    assert "rejected_sensitive" in capsys.readouterr().out
