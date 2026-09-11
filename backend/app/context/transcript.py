"""TranscriptStore: the session history on disk.

Storage is one JSONL file per session (state/sessions/<id>.jsonl). JSONL is
append-only, so a crash mid-write can only damage the LAST line; the reader
skips unparsable lines instead of losing the whole transcript.

Transcript is not Memory: it is the record of what was said, not what was
learned.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import TranscriptEntry, TranscriptSummary, utc_now


class TranscriptError(RuntimeError):
    """Raised when a transcript cannot be read or written."""


class TranscriptStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._counts: dict[str, int] = {}

    # -- paths -------------------------------------------------------------

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    # -- writing -----------------------------------------------------------

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        meta: dict | None = None,
        created_at: datetime | None = None,
    ) -> TranscriptEntry:
        entry = TranscriptEntry(
            index=self.next_index(session_id),
            session_id=session_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            created_at=created_at or utc_now(),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            meta=dict(meta or {}),
        )
        path = self.path_for(session_id)
        line = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._counts[session_id] = entry.index + 1
        return entry

    def next_index(self, session_id: str) -> int:
        """Index for the next message; survives a restart via the file tail."""
        cached = self._counts.get(session_id)
        if cached is not None:
            return cached
        entries = self.read(session_id)
        next_index = (entries[-1].index + 1) if entries else 0
        self._counts[session_id] = next_index
        return next_index

    # -- reading -----------------------------------------------------------

    def read(self, session_id: str) -> list[TranscriptEntry]:
        path = self.path_for(session_id)
        if not path.exists():
            return []
        entries: list[TranscriptEntry] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(TranscriptEntry.model_validate(json.loads(line)))
                except Exception:
                    # A torn final line (crash during append) must not make the
                    # whole transcript unreadable.
                    continue
        return entries

    def message_count(self, session_id: str) -> int:
        return len(self.read(session_id))

    def sessions(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.jsonl"))

    def delete(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        self._counts.pop(session_id, None)
        if path.exists():
            path.unlink()
            return True
        return False

    # -- turns -------------------------------------------------------------

    @staticmethod
    def split_turns(entries: list[TranscriptEntry]) -> list[list[TranscriptEntry]]:
        """Group entries into turns; a turn starts at each user message."""
        turns: list[list[TranscriptEntry]] = []
        current: list[TranscriptEntry] = []
        for entry in entries:
            if entry.role == "user" and current:
                turns.append(current)
                current = []
            current.append(entry)
        if current:
            turns.append(current)
        return turns

    def recent_turns(self, session_id: str, count: int) -> list[TranscriptEntry]:
        turns = self.split_turns(self.read(session_id))
        if count <= 0:
            return []
        return [entry for turn in turns[-count:] for entry in turn]

    # -- summarisation -----------------------------------------------------

    def summarize(
        self,
        session_id: str,
        keep_turns: int = 3,
        per_turn_chars: int = 180,
    ) -> TranscriptSummary:
        """Extractive summary of every turn except the newest 'keep_turns'.

        No model is involved: the summary is built from the first line of each
        older message, so it is deterministic and cheap. The original indices
        are preserved in the result so the full text can be re-read on demand.
        """
        entries = self.read(session_id)
        turns = self.split_turns(entries)
        if keep_turns < 0:
            keep_turns = 0
        old_turns = turns[: max(len(turns) - keep_turns, 0)]
        kept_turns = turns[len(turns) - keep_turns :] if keep_turns else []

        lines: list[str] = []
        summarized: list[int] = []
        for number, turn in enumerate(old_turns, start=1):
            first = turn[0]
            lines.append(f"turn {number} (idx {first.index}): {first.one_line(per_turn_chars)}")
            summarized.extend(entry.index for entry in turn)
            for reply in turn[1:]:
                if reply.role in ("assistant", "tool") and reply.content.strip():
                    label = reply.tool_name or reply.role
                    lines.append(f"  {label}: {reply.one_line(per_turn_chars)}")

        kept = [entry.index for turn in kept_turns for entry in turn]
        text = "\n".join(lines)
        return TranscriptSummary(
            session_id=session_id,
            text=text,
            summarized_indices=summarized,
            kept_indices=kept,
            summarized_count=len(summarized),
            kept_count=len(kept),
        )

    def write_summary(self, summary: TranscriptSummary, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    # -- archiving ---------------------------------------------------------

    def archive(self, session_id: str, destination: Path) -> Path:
        """Copy a transcript into the archive directory and return the path."""
        source = self.path_for(session_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            destination.write_text("", encoding="utf-8")
        return destination


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
