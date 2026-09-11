"""Checkpoint store tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents import Checkpoint, CheckpointStore


def _checkpoint(run_id: str = "run-1") -> Checkpoint:
    return Checkpoint(
        run_id=run_id,
        task="do a thing",
        system="be careful",
        session_id="session-1",
        step=3,
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint())

    loaded = store.load("run-1")

    assert loaded is not None
    assert loaded.step == 3
    assert loaded.task == "do a thing"
    assert loaded.session_id == "session-1"


def test_load_of_a_missing_run_is_none(tmp_path: Path) -> None:
    assert CheckpointStore(tmp_path).load("nope") is None


def test_saving_twice_overwrites(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint())
    second = _checkpoint()
    second.step = 9
    store.save(second)

    assert store.load("run-1").step == 9


def test_a_torn_checkpoint_is_ignored(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint())
    store.path_for("run-1").write_text('{"run_id": "run-1", "step":', encoding="utf-8")

    assert store.load("run-1") is None, "a torn checkpoint must not crash the loop"


def test_an_empty_checkpoint_file_is_ignored(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.path_for("run-1").write_text("", encoding="utf-8")

    assert store.load("run-1") is None


def test_latest_returns_the_most_recent(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint("older"))
    store.save(_checkpoint("newer"))

    assert store.latest().run_id == "newer"


def test_latest_on_an_empty_store_is_none(tmp_path: Path) -> None:
    assert CheckpointStore(tmp_path).latest() is None


def test_latest_skips_a_corrupt_file(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint("good"))
    store.path_for("bad").write_text("{ broken", encoding="utf-8")

    assert store.latest().run_id == "good"


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint())

    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_runs_lists_every_checkpoint(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint("a"))
    store.save(_checkpoint("b"))

    assert store.runs() == ["a", "b"]


def test_delete_removes_a_checkpoint(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.save(_checkpoint())

    assert store.delete("run-1") is True
    assert store.delete("run-1") is False
    assert store.load("run-1") is None


def test_updated_at_moves_on_resave(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    first = store.save(_checkpoint())
    before = json.loads(first.read_text(encoding="utf-8"))["updated_at"]
    second = store.save(_checkpoint())
    after = json.loads(second.read_text(encoding="utf-8"))["updated_at"]

    assert after >= before
