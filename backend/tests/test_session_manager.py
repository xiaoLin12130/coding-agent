"""SessionManager tests: lifecycle, persistence, rotation.

The last test is the M2 acceptance path itself:
save state -> close the program -> start again -> recover state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.context.models import MemoryProposal
from app.models import ProjectState, TodoItem
from app.storage import StateStore


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )


def _manager(tmp_path: Path, keep_turns: int = 3) -> SessionManager:
    return SessionManager(
        tmp_path / "sessions",
        store=StateStore(_paths(tmp_path)),
        keep_turns_on_rotation=keep_turns,
    )


# --- lifecycle ------------------------------------------------------------


def test_start_creates_a_session_and_index(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    snapshot = manager.start()

    assert snapshot.created is True
    assert snapshot.recovered is False
    assert snapshot.active_session_id
    assert (tmp_path / "sessions" / "index.json").exists()
    assert manager.current_session_id() == snapshot.active_session_id


def test_start_twice_resumes_the_same_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.start()
    manager.record("user", "hello")

    second = manager.start()

    assert second.active_session_id == first.active_session_id
    assert second.recovered is True
    assert second.created is False
    assert [e.content for e in second.entries] == ["hello"]


def test_start_with_explicit_id_opens_that_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    snapshot = manager.start(session_id="named-session")

    assert snapshot.active_session_id == "named-session"
    assert manager.start().active_session_id == "named-session"


def test_record_requires_an_active_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    entry = manager.record("user", "auto-started")

    assert entry.session_id == manager.current_session_id()
    assert entry.index == 0


def test_record_updates_the_index_counters(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    manager.record("user", "one")
    manager.record("assistant", "two")

    info = manager.sessions()[0]
    assert info.message_count == 2
    assert info.turn_count == 1


def test_record_keeps_tool_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    entry = manager.record("tool", "output", tool_name="read_file", tool_call_id="c1")

    assert entry.tool_name == "read_file"
    assert entry.tool_call_id == "c1"


def test_corrupt_index_is_rebuilt_from_transcripts(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    manager.record("user", "survives")
    session_id = manager.current_session_id()
    (tmp_path / "sessions" / "index.json").write_text("{ not json", encoding="utf-8")

    recovered = _manager(tmp_path)

    assert recovered.current_session_id() == session_id
    assert [e.content for e in recovered.transcript_of(session_id)] == ["survives"]


def test_index_with_wrong_shape_is_rebuilt(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    (tmp_path / "sessions" / "index.json").write_text(
        json.dumps({"sessions": "not-a-list"}), encoding="utf-8"
    )

    assert _manager(tmp_path).current_session_id() is not None


# --- rotation -------------------------------------------------------------


def test_should_rotate_only_at_the_threshold(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.should_rotate(999, 1000) is False
    assert manager.should_rotate(1000, 1000) is True
    assert manager.should_rotate(1, 0) is True


def test_rotate_archives_and_opens_a_seeded_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path, keep_turns=1)
    manager.start()
    for number in range(1, 5):
        manager.record("user", f"user {number}")
        manager.record("assistant", f"assistant {number}")
    manager.save_project_state(
        ProjectState(current_milestone="M2", current_task="keep going")
    )
    old_id = manager.current_session_id()

    rotation = manager.rotate()

    assert rotation.archived_session_id == old_id
    assert rotation.new_session_id != old_id
    assert manager.current_session_id() == rotation.new_session_id
    # the archive and summary were written
    assert Path(manager.sessions()[-2].archive_path).exists()
    assert Path(manager.sessions()[-2].summary_path).exists()
    assert manager.sessions()[-2].archived is True


def test_rotated_session_is_seeded_with_state_memory_task_and_summary(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path, keep_turns=1)
    manager.start()
    manager.record("user", "oldest question")
    manager.record("assistant", "oldest answer")
    manager.record("user", "newest question")
    manager.record("assistant", "newest answer")
    manager.memory.propose(MemoryProposal(key="stack", value="fastapi + react"))
    manager.save_project_state(
        ProjectState(
            current_milestone="M2",
            current_task="finish the builder",
            todos=[TodoItem(content="write builder", status="in_progress")],
        )
    )

    rotation = manager.rotate()
    seeded = manager.transcript.read(rotation.new_session_id)

    assert rotation.seed_entry_index == 0
    seed = seeded[0]
    assert seed.role == "system"
    assert seed.meta["kind"] == "session_seed"
    assert seed.meta["rotated_from"] == rotation.archived_session_id
    assert "current_milestone: M2" in seed.content
    assert "finish the builder" in seed.content
    assert "stack" in seed.content, "necessary memory must be carried over"
    assert "oldest question" in seed.content, "the summary must carry the old turn"


def test_seed_summary_is_bounded(tmp_path: Path) -> None:
    """A rotation seed must stay small, or it defeats the point of rotating."""
    manager = SessionManager(
        tmp_path / "sessions",
        store=StateStore(_paths(tmp_path)),
        keep_turns_on_rotation=1,
        seed_summary_chars=400,
    )
    manager.start()
    for number in range(20):
        manager.record("user", f"question {number} " + "x" * 200)
        manager.record("assistant", f"answer {number} " + "y" * 200)
    manager.save_project_state(ProjectState(current_milestone="M2", current_task="carry on"))

    rotation = manager.rotate()
    seed = manager.transcript.read(rotation.new_session_id)[0]

    assert rotation.summary.summarized_count > 0
    assert "earlier summary omitted" in seed.content
    # The whole seed stays near the cap plus the state/memory/task blocks.
    assert len(seed.content) < 4000
    # It keeps the NEWEST part of the summary, not the oldest.
    assert "question 18" in seed.content or "question 19" in seed.content


def test_rotation_carries_the_recent_turns_verbatim(tmp_path: Path) -> None:
    manager = _manager(tmp_path, keep_turns=2)
    manager.start()
    for number in range(1, 4):
        manager.record("user", f"u{number}")
        manager.record("assistant", f"a{number}")

    rotation = manager.rotate()
    carried = [
        e for e in manager.transcript.read(rotation.new_session_id)
        if e.meta.get("carried_from")
    ]

    # the last two turns (u2/a2, u3/a3) survive verbatim
    assert [e.content for e in carried] == ["u2", "a2", "u3", "a3"]
    assert rotation.carried_entry_indices == [e.index for e in carried]


def test_rotation_without_an_active_session_starts_one(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    rotation = manager.rotate()

    assert rotation.new_session_id
    assert manager.current_session_id() == rotation.new_session_id


def test_manual_rotation_records_its_reason(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    manager.record("user", "hi")

    rotation = manager.rotate(reason="context_budget")

    assert rotation.reason == "context_budget"
    seed = manager.transcript.read(rotation.new_session_id)[0]
    assert seed.meta["reason"] == "context_budget"


def test_rotation_persists_project_state_to_disk(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    manager.record("user", "hi")
    manager.save_project_state(ProjectState(current_milestone="M2"))

    manager.rotate()

    assert StateStore(_paths(tmp_path)).load_project_state().current_milestone == "M2"


def test_rotation_history_is_queryable(tmp_path: Path) -> None:
    manager = _manager(tmp_path, keep_turns=1)
    manager.start()
    manager.record("user", "old question")
    manager.record("assistant", "old answer")
    manager.record("user", "recent question")
    manager.record("assistant", "recent answer")

    rotation = manager.rotate(reason="manual")
    summary = manager.load_summary(rotation.archived_session_id)
    archived = manager.archived_sessions()

    assert summary is not None
    # the older turn is summarised; the newest one stays verbatim
    assert summary.summarized_count >= 1
    assert "old question" in summary.text
    assert [info.id for info in archived] == [rotation.archived_session_id]
    assert manager.load_summary("never-existed") is None


def test_context_budget_triggers_rotation_end_to_end(tmp_path: Path) -> None:
    """The documented sequence: context near the limit -> rotate."""
    manager = _manager(tmp_path, keep_turns=1)
    manager.start()
    for number in range(20):
        manager.record("user", f"question {number} " + "x" * 200)
        manager.record("assistant", f"answer {number} " + "y" * 200)
    manager.save_project_state(ProjectState(current_milestone="M2", current_task="carry on"))

    builder = ContextBuilder(
        manager.transcript, manager.memory, manager.store
    )
    context = builder.build(
        session_id=manager.current_session_id(), system="rules", task="carry on"
    )
    assert manager.should_rotate(context.total_chars, small_budget(context)) is True

    old_id = manager.current_session_id()
    rotation = manager.rotate(reason="context_budget")
    after = builder.build(
        session_id=manager.current_session_id(), system="rules", task="carry on"
    )

    assert rotation.archived_session_id == old_id
    assert after.total_chars < context.total_chars, "the new session starts small"
    # Rotation must actually reclaim space, not just move it into a seed.
    assert after.total_chars < context.total_chars / 2
    assert "carry on" in after.section("task").content


def small_budget(context) -> int:
    return max(context.total_chars // 2, 1)


# --- the M2 acceptance path ----------------------------------------------


def test_acceptance_save_close_restart_recover(tmp_path: Path) -> None:
    """M2 acceptance: 保存状态 -> 关闭程序 -> 重新启动 -> 恢复状态."""
    session_id: str

    # --- run 1: work happens, state is saved ---------------------------------
    first = _manager(tmp_path)
    first.start()
    first.record("user", "implement M2")
    first.record("assistant", "context layer done")
    first.record("tool", "22 passed", tool_name="pytest")
    first.memory.propose(
        MemoryProposal(key="suite", value="backend pytest is the gate")
    )
    first.save_project_state(
        ProjectState(
            current_milestone="M2",
            current_task="finish the builder",
            todos=[TodoItem(content="write builder", status="completed")],
            files_changed=["backend/app/context/builder.py"],
        )
    )
    session_id = first.current_session_id()
    first = None  # the program closes

    # --- run 2: a brand new process reads what run 1 left behind -------------
    second = _manager(tmp_path)
    snapshot = second.start()
    assert snapshot.active_session_id == session_id
    assert snapshot.recovered is True
    assert [e.content for e in snapshot.entries] == [
        "implement M2",
        "context layer done",
        "22 passed",
    ]

    state = second.store.load_project_state()
    assert state.current_milestone == "M2"
    assert state.current_task == "finish the builder"
    assert state.todos[0].status == "completed"
    assert second.memory.get("suite").value == "backend pytest is the gate"

    # ...and the context for the next turn is built from the restored data
    builder = ContextBuilder(second.transcript, second.memory, second.store)
    context = builder.build(
        session_id=snapshot.active_session_id,
        system="system rules",
        task=state.current_task,
    )

    assert "current_milestone: M2" in context.section("project_state").content
    assert "suite" in context.section("memory").content
    assert "implement M2" in context.section("transcript").content
    assert "system rules" in context.section("system").content


def test_restart_continues_appending_to_the_same_transcript(tmp_path: Path) -> None:
    first = _manager(tmp_path)
    first.start()
    first.record("user", "before restart")
    session_id = first.current_session_id()

    second = _manager(tmp_path)
    second.start()
    entry = second.record("user", "after restart")

    assert entry.session_id == session_id
    assert entry.index == 1, "numbering continues across the restart"
    assert [e.content for e in second.transcript_of(session_id)] == [
        "before restart",
        "after restart",
    ]


def test_deleted_transcript_starts_a_fresh_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.start()
    manager.record("user", "gone soon")
    old_id = manager.current_session_id()
    manager.transcript.delete(old_id)

    restarted = _manager(tmp_path)
    snapshot = restarted.start()

    assert snapshot.active_session_id != old_id
    assert snapshot.created is True
    assert snapshot.entries == []
