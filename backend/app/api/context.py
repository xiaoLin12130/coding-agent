"""Context / session REST surface (M2).

Read-only by design: M2 exposes what the context layer already persisted so
the console can show it. Nothing here writes state, and no endpoint can
execute a tool — the Tool layer arrives in M3 behind SafetyLayer/Executor.

Named after docs/api-protocol.md (/api/sessions, /api/messages), keeping the
existing /api/project_state and /api/memory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import ContextBuilder, SessionManager
from ..context.models import (
    BuiltContext,
    SessionInfo,
    SessionSnapshot,
    TranscriptEntry,
)
from ..deps import get_session_manager

router = APIRouter()


class SessionListResponse(dict):
    """Documentation-only marker; the payload is built inline."""


@router.get("/sessions")
def list_sessions(manager: SessionManager = Depends(get_session_manager)) -> dict:
    snapshot = manager.start()
    sessions = manager.sessions()
    return {
        "active_session_id": snapshot.active_session_id,
        "recovered": snapshot.recovered,
        "sessions": [info.model_dump(mode="json") for info in sessions],
    }


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str, manager: SessionManager = Depends(get_session_manager)
) -> SessionSnapshot:
    info: SessionInfo | None = None
    for candidate in manager.sessions():
        if candidate.id == session_id:
            info = candidate
            break
    if info is None and not manager.transcript.path_for(session_id).exists():
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    entries = manager.transcript_of(session_id)
    return SessionSnapshot(
        active_session_id=session_id,
        entries=entries,
        message_count=len(entries),
        turn_count=len(manager.transcript.split_turns(entries)),
    )


@router.get("/messages")
def list_messages(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    target = session_id or manager.start().active_session_id
    if target is None:
        raise HTTPException(status_code=404, detail="no active session")
    entries: list[TranscriptEntry] = manager.transcript_of(target)
    return {
        "session_id": target,
        "message_count": len(entries),
        "messages": [e.model_dump(mode="json") for e in entries[-limit:]],
    }


@router.get("/context", response_model=BuiltContext)
def preview_context(
    task: str = Query(default="", description="current task for this turn"),
    system: str = Query(default="You are a helpful software engineer assistant."),
    memory_query: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    manager: SessionManager = Depends(get_session_manager),
) -> BuiltContext:
    """Preview exactly what the next turn would send (budget applied).

    Read-only: it assembles the context and returns it without calling a model.
    """
    target = session_id or manager.start().active_session_id
    builder = ContextBuilder(manager.transcript, manager.memory, manager.store)
    return builder.build(
        session_id=target or "",
        system=system,
        task=task,
        memory_query=memory_query,
    )
