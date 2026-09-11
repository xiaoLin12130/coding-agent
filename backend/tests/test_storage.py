"""StateStore tests: round trip, atomic write, malformed file, missing files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppPaths
from app.models import Memory, ProjectState, TodoItem
from app.storage import StateStore, StateStoreError


def _paths(directory: Path) -> AppPaths:
    return AppPaths(
        project_root=directory,
        state_dir=directory,
        project_state_file=directory / "project_state.json",
        memory_file=directory / "memory.json",
    )


def test_missing_files_yield_empty_defaults(tmp_path: Path) -> None:
    store = StateStore(_paths(tmp_path))
    assert store.load_project_state() == ProjectState()
    assert store.load_memory() == Memory()


def test_empty_file_yields_defaults(tmp_path: Path) -> None:
    (tmp_path / "project_state.json").write_text("", encoding="utf-8")
    store = StateStore(_paths(tmp_path))
    assert store.load_project_state().current_milestone is None


def test_project_state_round_trip(tmp_path: Path) -> None:
    store = StateStore(_paths(tmp_path))
    state = ProjectState(
        current_milestone="M0",
        current_task="T1",
        todos=[TodoItem(content="skeleton", status="in_progress")],
        files_changed=["backend/app/main.py"],
        decisions=["fastapi + react"],
    )
    store.save_project_state(state)
    loaded = StateStore(_paths(tmp_path)).load_project_state()
    assert loaded == state
    assert loaded.todos[0].status == "in_progress"


def test_memory_round_trip(tmp_path: Path) -> None:
    # M2 made memory entries typed (MemoryEntry), so a written entry now
    # carries the entry defaults instead of the verbatim input object.
    store = StateStore(_paths(tmp_path))
    store.save_memory(Memory(memories=[{"key": "k", "value": "v"}]))
    raw = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
    assert raw["memories"][0]["key"] == "k"
    assert raw["memories"][0]["value"] == "v"

    loaded = store.load_memory().memories[0]
    assert loaded.key == "k"
    assert loaded.value == "v"
    assert loaded.namespace == "user"
    assert loaded.sensitive is False


def test_write_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    store = StateStore(_paths(tmp_path))
    store.save_project_state(ProjectState(current_milestone="M0"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_unknown_fields_are_preserved(tmp_path: Path) -> None:
    (tmp_path / "project_state.json").write_text(
        json.dumps({"current_milestone": "M0", "custom_future_field": 42}),
        encoding="utf-8",
    )
    store = StateStore(_paths(tmp_path))
    state = store.load_project_state()
    assert state.model_extra is not None
    assert state.model_extra["custom_future_field"] == 42


def test_malformed_json_raises(tmp_path: Path) -> None:
    (tmp_path / "project_state.json").write_text("{ not json", encoding="utf-8")
    store = StateStore(_paths(tmp_path))
    with pytest.raises(StateStoreError):
        store.load_project_state()
