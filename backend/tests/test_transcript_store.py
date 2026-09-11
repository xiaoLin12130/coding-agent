"""TranscriptStore tests: append/read, torn lines, turns, summaries, archive."""

from __future__ import annotations

import json
from pathlib import Path

from app.context.transcript import TranscriptStore


def test_append_assigns_increasing_indices(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    first = store.append("s1", "user", "hello")
    second = store.append("s1", "assistant", "hi")

    assert (first.index, second.index) == (0, 1)
    assert second.session_id == "s1"


def test_read_returns_entries_in_order(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "one")
    store.append("s1", "assistant", "two")
    store.append("s1", "tool", "three", tool_name="read_file")

    entries = store.read("s1")
    assert [e.content for e in entries] == ["one", "two", "three"]
    assert entries[2].tool_name == "read_file"


def test_missing_transcript_reads_empty(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    assert store.read("nope") == []
    assert store.message_count("nope") == 0


def test_index_survives_a_restart(tmp_path: Path) -> None:
    TranscriptStore(tmp_path).append("s1", "user", "hello")

    # A fresh store instance (a new process) must continue the numbering.
    restarted = TranscriptStore(tmp_path)
    entry = restarted.append("s1", "assistant", "world")
    assert entry.index == 1


def test_torn_final_line_does_not_lose_the_transcript(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "complete")
    store.append("s1", "assistant", "also complete")
    path = store.path_for("s1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"index": 2, "session_id": "s1", "rol')  # crash mid-write

    entries = store.read("s1")
    assert [e.content for e in entries] == ["complete", "also complete"]


def test_unknown_fields_in_a_line_are_skipped_not_fatal(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "good")
    path = store.path_for("s1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"totally": "different"}) + "\n")

    assert [e.content for e in store.read("s1")] == ["good"]


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "good")
    with store.path_for("s1").open("a", encoding="utf-8") as handle:
        handle.write("\n\n")

    assert len(store.read("s1")) == 1


def test_split_turns_groups_by_user_message(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "turn one")
    store.append("s1", "assistant", "reply one")
    store.append("s1", "user", "turn two")
    store.append("s1", "assistant", "reply two")
    store.append("s1", "assistant", "still turn two")

    turns = store.split_turns(store.read("s1"))
    assert len(turns) == 2
    assert [len(t) for t in turns] == [2, 3]


def test_recent_turns_returns_whole_turns(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    for number in range(1, 4):
        store.append("s1", "user", f"u{number}")
        store.append("s1", "assistant", f"a{number}")

    recent = store.recent_turns("s1", 2)
    assert [e.content for e in recent] == ["u2", "a2", "u3", "a3"]
    assert store.recent_turns("s1", 0) == []


def test_summarize_keeps_recent_turns_and_indexes(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    for number in range(1, 5):
        store.append("s1", "user", f"user message {number}")
        store.append("s1", "assistant", f"assistant reply {number}")

    summary = store.summarize("s1", keep_turns=2)

    assert summary.summarized_count == 4  # turns 1 and 2
    assert summary.kept_count == 4  # turns 3 and 4
    assert "user message 1" in summary.text
    assert "assistant reply 1" in summary.text
    assert "user message 3" not in summary.text, "recent turns must not be summarised"
    assert summary.summarized_indices == [0, 1, 2, 3]
    assert summary.kept_indices == [4, 5, 6, 7]


def test_summarize_with_keep_turns_zero_summarises_everything(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "only")
    summary = store.summarize("s1", keep_turns=0)

    assert summary.kept_count == 0
    assert "only" in summary.text


def test_summarize_of_empty_transcript_is_empty(tmp_path: Path) -> None:
    summary = TranscriptStore(tmp_path).summarize("empty", keep_turns=3)
    assert summary.text == ""
    assert summary.summarized_count == 0


def test_archive_copies_the_transcript(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "archive me")
    destination = tmp_path / "archive" / "s1.jsonl"

    path = store.archive("s1", destination)

    assert path == destination
    assert "archive me" in destination.read_text(encoding="utf-8")


def test_archive_of_missing_session_writes_an_empty_file(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    path = store.archive("ghost", tmp_path / "archive" / "ghost.jsonl")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_sessions_lists_transcripts(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("b", "user", "x")
    store.append("a", "user", "y")

    assert store.sessions() == ["a", "b"]


def test_delete_removes_the_transcript(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    store.append("s1", "user", "bye")

    assert store.delete("s1") is True
    assert store.delete("s1") is False
    assert store.read("s1") == []
