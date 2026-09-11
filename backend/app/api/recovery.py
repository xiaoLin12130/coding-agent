"""Recovery REST surface (M6).

Read-only. A client that lost its WebSocket (or restarted) reads the current
facts here instead of keeping them in memory: the active session, the archived
ones, the saved memory, the latest unfinished run and the context pressure.

Nothing here mutates state and nothing executes a tool.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..agents.checkpoint import CheckpointStore
from ..context import SessionManager
from ..deps import get_session_manager
from ..recovery import (
    ContextPressurePolicy,
    RecoverySnapshot,
    RunRecovery,
    RunRecoveryPlan,
    build_snapshot,
)
from ..recovery.models import ContextThresholds

router = APIRouter()


@router.get("/recovery", response_model=RecoverySnapshot)
def recovery_snapshot(
    task: str = Query(default="", description="current task, for the pressure reading"),
    system: str = Query(default=""),
    manager: SessionManager = Depends(get_session_manager),
) -> RecoverySnapshot:
    """Everything a reconnecting client needs to re-render."""
    return build_snapshot(sessions=manager, system=system, task=task)


@router.get("/recovery/runs", response_model=list[RunRecoveryPlan])
def pending_runs() -> list[RunRecoveryPlan]:
    """Runs that did not finish and can be continued."""
    return RunRecovery(CheckpointStore()).pending()


@router.get("/recovery/runs/{run_id}", response_model=RunRecoveryPlan)
def run_plan(run_id: str) -> RunRecoveryPlan:
    plan = RunRecovery(CheckpointStore()).plan(run_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="no checkpoint for run " + run_id)
    return plan


@router.get("/recovery/pressure")
def context_pressure(
    task: Annotated[str, Query()] = "",
    system: Annotated[str, Query()] = "You are a helpful software engineer assistant.",
    soft_ratio: Annotated[float, Query(gt=0, le=1)] = 0.7,
    hard_ratio: Annotated[float, Query(gt=0, le=1)] = 0.9,
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    """How full the next turn's context would be."""
    from ..context import ContextBuilder

    try:
        thresholds = ContextThresholds(soft_ratio=soft_ratio, hard_ratio=hard_ratio)
        policy = ContextPressurePolicy(thresholds)
    except ValueError as exc:
        # An inverted pair is a bad request, not a server error.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    builder = ContextBuilder(manager.transcript, manager.memory, manager.store)
    snapshot = manager.start()
    context = builder.build(
        session_id=snapshot.active_session_id or "", system=system, task=task
    )
    return policy.evaluate(context, builder.budget.max_chars).model_dump(mode="json")
