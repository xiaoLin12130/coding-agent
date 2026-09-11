"""Session recovery: the Context-full sequence and its injections (M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.context.models import MemoryProposal
from app.models import ProjectState, TodoItem
from app.recovery import SessionRecovery
from app.storage import StateStore


@pytest.fixture()
def env(tmp_path: Path):
    paths = AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )
    store = StateStore(paths)
    sessions = SessionManager(tmp_path / "sessions", store=store, keep_turns_on_rotation=2)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    return tmp_path, store, sessions, builder


def test_rotate_runs_the_documented_sequence(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    for number in range(1, 5):
        sessions.record("user", "question " + str(number))
        sessions.record("assistant", "answer " + str(number))
    sessions.save_project_state(
        ProjectState(current_milestone="M6", current_task="finish recovery")
    )
    old_id = sessions.current_session_id()

    report = SessionRecovery(sessions, builder).rotate(reason="context_budget")

    assert report.kind == "context_hard"
    assert report.recovered is True
    actions = report.notes()
    assert any("summarised" in action for action in actions)
    assert any("archived" in action for action in actions)
    assert any("opened session" in action for action in actions)
    assert report.context["archived_session_id"] == old_id
    assert report.context["new_session_id"] != old_id


def test_rotate_verifies_the_injections(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    sessions.record("user", "an older question")
    sessions.record("assistant", "an older answer")
    sessions.record("user", "a recent question")
    sessions.record("assistant", "a recent answer")
    sessions.memory.propose(MemoryProposal(key="gate", value="pytest is the gate"))
    sessions.save_project_state(
        ProjectState(
            current_milestone="M6",
            current_task="finish recovery",
            todos=[TodoItem(content="write recovery", status="in_progress")],
        )
    )

    report = SessionRecovery(sessions, builder).rotate()

    injections = report.context["injections"]
    assert injections == {
        "project state": True,
        "memory": True,
        "recent transcript": True,
        "current task": True,
    }
    assert report.recovered is True


def test_the_new_session_seed_carries_state_memory_task_and_recent_turns(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    sessions.record("user", "old question")
    sessions.record("assistant", "old answer")
    sessions.record("user", "new question")
    sessions.record("assistant", "new answer")
    sessions.memory.propose(MemoryProposal(key="stack", value="fastapi"))
    sessions.save_project_state(
        ProjectState(current_milestone="M6", current_task="carry on with recovery")
    )

    report = SessionRecovery(sessions, builder).rotate()
    new_id = report.context["new_session_id"]
    entries = sessions.transcript.read(new_id)

    seed = entries[0]
    assert seed.meta["kind"] == "session_seed"
    assert "current_milestone: M6" in seed.content
    assert "carry on with recovery" in seed.content
    assert "stack" in seed.content, "memory must be injected"

    carried = [entry for entry in entries if entry.meta.get("carried_from")]
    assert carried, "the recent turns must be carried verbatim"
    assert carried[-1].content == "new answer"


def test_the_archived_session_is_recorded(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    sessions.record("user", "old")
    old_id = sessions.current_session_id()

    report = SessionRecovery(sessions, builder).rotate()

    archived = sessions.archived_sessions()
    assert [info.id for info in archived] == [old_id]
    assert Path(archived[0].archive_path).exists()
    assert Path(archived[0].summary_path).exists()
    assert sessions.load_summary(old_id) is not None
    assert report.context["summary_chars"] >= 0


def test_rotation_reclaims_context(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    for number in range(30):
        sessions.record("user", "long question " + str(number) + " " + "x" * 200)
        sessions.record("assistant", "long answer " + str(number) + " " + "y" * 200)
    sessions.save_project_state(ProjectState(current_milestone="M6", current_task="carry on"))

    recovery = SessionRecovery(sessions, builder)
    before = recovery.evaluate(
        sessions.current_session_id() or "", system="s", task="carry on"
    )
    report = recovery.rotate()
    after = recovery.evaluate(
        sessions.current_session_id() or "", system="s", task="carry on"
    )

    assert report.recovered is True
    assert after.used_chars < before.used_chars
    assert after.level != "hard", "the fresh session must not still be full"


def test_rotate_without_a_session_starts_one(env) -> None:
    _tmp, _store, sessions, builder = env

    report = SessionRecovery(sessions, builder).rotate()

    assert report.recovered is True
    assert sessions.current_session_id()


def test_an_empty_rotation_is_not_reported_as_a_failure(env) -> None:
    """Nothing to inject is not the same as failed to inject."""
    _tmp, _store, sessions, builder = env
    sessions.start()

    report = SessionRecovery(sessions, builder).rotate()

    assert report.recovered is True
    assert all(report.context["injections"].values())


def test_a_missing_injection_is_reported_as_a_failure(env) -> None:
    """When the seed loses data that existed, the check must fail."""
    import json

    _tmp, store, sessions, builder = env
    sessions.start()
    sessions.record("user", "hello")
    sessions.save_project_state(
        ProjectState(current_milestone="M6", current_task="finish recovery")
    )

    recovery = SessionRecovery(sessions, builder)
    report = recovery.rotate()
    assert report.recovered is True
    assert report.context["injections"]["project state"] is True

    # Strip the seed from the new session: the data that was there is now gone.
    new_id = report.context["new_session_id"]
    path = sessions.transcript.path_for(new_id)
    kept = [
        entry
        for entry in sessions.transcript.read(new_id)
        if entry.meta.get("kind") != "session_seed"
    ]
    path.write_text(
        "".join(
            json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + chr(10)
            for entry in kept
        ),
        encoding="utf-8",
    )

    injections = SessionRecovery(sessions, builder).injections(
        new_id, task="finish recovery"
    )
    assert injections["project state"] is False, "the project state is no longer injected"
    assert injections["current task"] is False


def test_soft_pressure_reduces_recent_turns(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    builder.recent_turns = 5

    report = SessionRecovery(sessions, builder).apply_soft(default_recent_turns=5)

    assert report.kind == "context_soft"
    assert builder.recent_turns == 2
    assert report.context == {"recent_turns": 2, "previous": 5}


def test_soft_pressure_is_a_no_op_when_already_small(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()
    builder.recent_turns = 1

    report = SessionRecovery(sessions, builder).apply_soft(default_recent_turns=1)

    assert report.outcome == "not_needed"
    assert builder.recent_turns == 1


def test_evaluate_reports_the_pressure_level(env) -> None:
    _tmp, _store, sessions, builder = env
    sessions.start()

    pressure = SessionRecovery(sessions, builder).evaluate(
        sessions.current_session_id() or "", system="s", task="t"
    )

    assert pressure.level == "ok"
    assert pressure.budget_chars == builder.budget.max_chars
