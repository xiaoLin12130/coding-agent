"""SessionManager: sessions that survive a restart.

A Session is one complete dialogue execution environment. docs/state-context.md
defines what must happen when its context approaches the hard threshold:

    finish the turn -> save Project State -> summarise the old transcript
    -> archive the session -> open a new session seeded with
       Project State + necessary Memory + the last 2-3 turns + the current task

so a task continues across the boundary instead of restarting from nothing.

Everything needed to resume lives on disk (state/sessions/index.json plus one
JSONL transcript per session), which is what makes the M2 acceptance path
work: save state, close the program, start again, recover state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import sessions_dir as default_sessions_dir
from ..models import ProjectState
from ..storage import StateStore
from .builder import render_project_state
from .memory import MemoryStore
from .models import (
    SessionIndex,
    SessionInfo,
    SessionRotation,
    SessionSnapshot,
)
from .transcript import TranscriptStore

INDEX_NAME = "index.json"
ARCHIVE_DIR = "archive"
SUMMARIES_DIR = "summaries"

ROTATION_REASON_BUDGET = "context_budget"
ROTATION_REASON_MANUAL = "manual"
ROTATION_REASON_MISSING = "transcript_missing"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def tail_clip(text: str, limit: int) -> str:
    """Keep the END of text (the most recent turns) within limit chars."""
    if limit <= 0 or len(text) <= limit:
        return text
    kept = text[-limit:]
    # Start on a line boundary so the seed never begins mid-sentence.
    newline = kept.find("\n")
    if 0 <= newline < 200:
        kept = kept[newline + 1 :]
    return f"...[earlier summary omitted; full text in the summary file]...\n{kept}"


def new_session_id() -> str:
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    # A short random suffix keeps two sessions created in the same second apart.
    import os

    return f"session-{stamp}-{os.urandom(2).hex()}"


class SessionManager:
    def __init__(
        self,
        root: Path | str | None = None,
        store: StateStore | None = None,
        keep_turns_on_rotation: int = 3,
        seed_summary_chars: int = 1500,
    ) -> None:
        self.root = Path(root) if root is not None else default_sessions_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store or StateStore()
        self.transcript = TranscriptStore(self.root)
        self.memory = MemoryStore(self.store)
        self.keep_turns_on_rotation = keep_turns_on_rotation
        # The seed carries a BOUNDED summary. Embedding the whole summary
        # would rebuild a context as large as the one rotation exists to
        # escape, so the newest part of it is kept and the rest stays on disk.
        self.seed_summary_chars = seed_summary_chars
        self._index = self._read_index()

    # -- index persistence -------------------------------------------------

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    def _read_index(self) -> SessionIndex:
        if not self.index_path.exists():
            return SessionIndex()
        raw = self.index_path.read_text(encoding="utf-8")
        if not raw.strip():
            return SessionIndex()
        try:
            return SessionIndex.model_validate(json.loads(raw))
        except Exception:
            # A corrupt index must not make the agent unusable: transcripts
            # are the source of truth, so rebuild from them.
            return self._rebuild_index()

    def _rebuild_index(self) -> SessionIndex:
        sessions = [
            SessionInfo(id=session_id) for session_id in self.transcript.sessions()
        ]
        index = SessionIndex(
            active_session_id=sessions[-1].id if sessions else None,
            sessions=sessions,
        )
        self._write_index(index)
        return index

    def _write_index(self, index: SessionIndex | None = None) -> None:
        if index is not None:
            self._index = index
        self.index_path.write_text(
            json.dumps(self._index.model_dump(mode="json"), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    # -- session lifecycle -------------------------------------------------

    def current_session_id(self) -> str | None:
        return self._index.active_session_id

    def sessions(self) -> list[SessionInfo]:
        return list(self._index.sessions)

    def start(self, session_id: str | None = None, title: str = "") -> SessionSnapshot:
        """Open a session, resuming the active one when it still exists.

        This is the restart entry point: called on a fresh process it returns
        the transcript written by the previous run.
        """
        target = session_id or self._index.active_session_id
        created = False
        recovered = False

        if target is None or not self.transcript.path_for(target).exists():
            target = session_id or new_session_id()
            created = session_id is None or not self.transcript.path_for(target).exists()
            info = SessionInfo(id=target, title=title or "Default Session")
            self._index.sessions.append(info)
            # Touch the file so an empty session is still resumable.
            self.transcript.path_for(target).touch()
        else:
            info = self._index.find(target)
            recovered = True
            if info is None:
                info = SessionInfo(id=target, title=title or "Default Session")
                self._index.sessions.append(info)

        self._index.active_session_id = target
        entries = self.transcript.read(target)
        info.message_count = len(entries)
        info.turn_count = len(self.transcript.split_turns(entries))
        info.updated_at = _now()
        self._write_index()

        return SessionSnapshot(
            active_session_id=target,
            created=created,
            recovered=recovered,
            entries=entries,
            message_count=len(entries),
            turn_count=info.turn_count,
            archived_session_ids=[
                s.id for s in self._index.sessions if s.archived
            ],
        )

    def resume_or_create(self, session_id: str | None = None) -> SessionSnapshot:
        """Alias used by callers that do not care whether it was created."""
        return self.start(session_id=session_id)

    # -- recording ---------------------------------------------------------

    def record(
        self,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        meta: dict | None = None,
    ):
        session_id = self._index.active_session_id
        if session_id is None:
            session_id = self.start().active_session_id
        entry = self.transcript.append(
            session_id,
            role,
            content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            meta=meta,
        )
        info = self._index.find(session_id)
        if info is not None:
            info.message_count = self.transcript.message_count(session_id)
            info.turn_count = len(
                self.transcript.split_turns(self.transcript.read(session_id))
            )
            info.updated_at = _now()
            self._write_index()
        return entry

    def save_project_state(self, state: ProjectState) -> None:
        """Persist project state — the step the rotation sequence requires."""
        self.store.save_project_state(state)

    # -- rotation ----------------------------------------------------------

    def should_rotate(self, used_chars: int, budget_chars: int) -> bool:
        """True once the assembled context reaches the hard threshold."""
        if budget_chars <= 0:
            return True
        return used_chars >= budget_chars

    def rotate(
        self,
        reason: str = ROTATION_REASON_BUDGET,
        project_state: ProjectState | None = None,
        title: str = "",
    ) -> SessionRotation:
        """Archive the active session and open a seeded continuation."""
        old_id = self._index.active_session_id
        if old_id is None or not self.transcript.path_for(old_id).exists():
            snapshot = self.start()
            old_id = snapshot.active_session_id

        # 1. Project State is already on disk (the caller saved it); make sure
        #    the file matches what this rotation will seed from.
        state = project_state or self.store.load_project_state()

        # 2. summary of the old transcript
        summary = self.transcript.summarize(
            old_id, keep_turns=self.keep_turns_on_rotation
        )
        summary_path = self.root / SUMMARIES_DIR / f"{old_id}.json"
        self.transcript.write_summary(summary, summary_path)

        # 3. archive the transcript
        archive_path = self.transcript.archive(
            old_id, self.root / ARCHIVE_DIR / f"{old_id}.jsonl"
        )

        # 4. open the new session
        new_id = new_session_id()
        info = SessionInfo(id=new_id, title=title or f"continued from {old_id}", rotated_from=old_id)
        self._index.sessions.append(info)
        self._index.active_session_id = new_id
        self.transcript.path_for(new_id).touch()

        old_info = self._index.find(old_id)
        if old_info is not None:
            old_info.archived = True
            old_info.summary_path = str(summary_path)
            old_info.archive_path = str(archive_path)
            old_info.updated_at = _now()

        # 5. seed the new session so the task continues, not restarts.
        seed_parts = [
            self._seed_text(state, summary)
        ]
        seed = "\n\n".join(part for part in seed_parts if part.strip())
        seed_entry = self.transcript.append(
            new_id,
            "system",
            seed,
            meta={
                "kind": "session_seed",
                "rotated_from": old_id,
                "reason": reason,
                "summary_path": str(summary_path),
                "archive_path": str(archive_path),
            },
        )

        # 5b. carry the last turns across verbatim so the agent keeps the
        #     immediate conversational context, not just a summary of it.
        carried: list[int] = []
        for entry in self.transcript.recent_turns(
            old_id, self.keep_turns_on_rotation
        ):
            copied = self.transcript.append(
                new_id,
                entry.role,
                entry.content,
                tool_name=entry.tool_name,
                tool_call_id=entry.tool_call_id,
                meta={**entry.meta, "carried_from": old_id, "carried_index": entry.index},
            )
            carried.append(copied.index)

        info.message_count = self.transcript.message_count(new_id)
        info.updated_at = _now()
        self._write_index()

        return SessionRotation(
            archived_session_id=old_id,
            new_session_id=new_id,
            reason=reason,
            summary=summary,
            carried_entry_indices=carried,
            seed_entry_index=seed_entry.index,
        )

    def _seed_text(self, state: ProjectState, summary) -> str:
        """Project State + necessary Memory + current task, per the spec."""
        parts = [
            "## Session continuation",
            "This session continues an archived one. The task must carry on, "
            "not restart.",
            "## Project state",
            render_project_state(state),
        ]
        memory_text = self.memory_text_for_seed()
        if memory_text:
            parts.append("## Remembered facts")
            parts.append(memory_text)
        if state.current_task:
            parts.append("## Current task")
            parts.append(state.current_task)
        if summary.text:
            parts.append("## Summary of the archived transcript")
            parts.append(tail_clip(summary.text, self.seed_summary_chars))
        return "\n\n".join(parts)

    def memory_text_for_seed(self) -> str:
        entries = self.memory.all()
        if not entries:
            return ""
        return "\n".join(
            f"- {entry.namespace}/{entry.key}: {entry.value}" for entry in entries
        )

    # -- maintenance -------------------------------------------------------

    def archived_sessions(self) -> list[SessionInfo]:
        return [info for info in self._index.sessions if info.archived]

    def load_summary(self, session_id: str):
        info = self._index.find(session_id)
        if info is None or not info.summary_path:
            return None
        path = Path(info.summary_path)
        if not path.exists():
            return None
        from .models import TranscriptSummary

        return TranscriptSummary.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def transcript_of(self, session_id: str):
        return self.transcript.read(session_id)
