"""Re-sync snapshot for a reconnecting client (WebSocket disconnect).

The server keeps no essential state in memory: sessions, transcripts, memory
and checkpoints are all on disk. So a client that lost its WebSocket only needs
to read the current facts again — which is what this builds.
"""

from __future__ import annotations

from ..agents.checkpoint import CheckpointStore
from ..context.builder import ContextBuilder
from ..context.session import SessionManager
from .models import RecoverySnapshot
from .run_recovery import RunRecovery
from .thresholds import ContextPressurePolicy


def build_snapshot(
    sessions: SessionManager | None = None,
    checkpoints: CheckpointStore | None = None,
    system: str = "",
    task: str = "",
    policy: ContextPressurePolicy | None = None,
) -> RecoverySnapshot:
    """Everything a client needs to re-render after a reconnect."""
    sessions = sessions or SessionManager()
    checkpoints = checkpoints or CheckpointStore()

    snapshot = sessions.start()
    session_id = snapshot.active_session_id

    context_pressure = None
    if task or system:
        builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
        context = builder.build(session_id=session_id, system=system, task=task)
        context_pressure = (policy or ContextPressurePolicy()).evaluate(
            context, builder.budget.max_chars
        )

    return RecoverySnapshot(
        active_session_id=session_id,
        session_message_count=snapshot.message_count,
        archived_session_ids=[info.id for info in sessions.sessions() if info.archived],
        memory_count=sessions.memory.count(),
        latest_run=RunRecovery(checkpoints, sessions).plan(),
        context_pressure=context_pressure,
    )
