"""Run recovery: continue after the program restarted.

M5 writes a checkpoint after every step. M6 is what turns that into "the task
continues after a crash or a restart": find the latest unfinished run, rebuild
its session, and hand it back to a fresh loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agents.checkpoint import CheckpointStore
from ..context.session import SessionManager
from .models import RecoveryReport, RecoveryStep, RunRecoveryPlan


class RunRecovery:
    def __init__(
        self,
        checkpoints: CheckpointStore | None = None,
        sessions: SessionManager | None = None,
    ) -> None:
        self.checkpoints = checkpoints or CheckpointStore()
        self.sessions = sessions

    # -- what is there to recover? ----------------------------------------

    def plan(self, run_id: str | None = None) -> RunRecoveryPlan | None:
        """The run that would be continued, or None when there is nothing to do."""
        checkpoint = (
            self.checkpoints.load(run_id) if run_id else self.checkpoints.latest()
        )
        if checkpoint is None:
            return None

        resumable = checkpoint.status != "completed"
        reason = "" if resumable else "the run already finished"
        if resumable and self.sessions is not None:
            path = self.sessions.transcript.path_for(checkpoint.session_id)
            if not path.exists():
                # The session is gone: the checkpoint can still be replayed, but
                # the transcript it refers to is not there any more.
                reason = "the session transcript is missing; a new session will be used"
        return RunRecoveryPlan(
            run_id=checkpoint.run_id,
            task=checkpoint.task,
            step=checkpoint.step,
            session_id=checkpoint.session_id,
            status=checkpoint.status,
            checkpoint_path=str(self.checkpoints.path_for(checkpoint.run_id)),
            resumable=resumable,
            reason=reason,
            updated_at=checkpoint.updated_at,
        )

    def pending(self) -> list[RunRecoveryPlan]:
        """Every run that did not finish, newest first."""
        plans: list[RunRecoveryPlan] = []
        for run_id in self.checkpoints.runs():
            plan = self.plan(run_id)
            if plan is not None and plan.resumable:
                plans.append(plan)
        plans.sort(key=lambda item: item.updated_at or item.checkpoint_path, reverse=True)
        return plans

    # -- doing it ----------------------------------------------------------

    def resume(self, loop: Any, run_id: str | None = None) -> tuple[Any, RecoveryReport]:
        """Continue a run with a freshly built loop (a new process)."""
        plan = self.plan(run_id)
        steps: list[RecoveryStep] = []

        if plan is None:
            return None, RecoveryReport(
                kind="program_restart",
                outcome="not_needed",
                message="no checkpoint to resume",
            )
        if not plan.resumable:
            return None, RecoveryReport(
                kind="program_restart",
                outcome="not_needed",
                message=plan.reason or "the run already finished",
                context={"run_id": plan.run_id},
            )

        steps.append(
            RecoveryStep(
                action="found checkpoint",
                detail=plan.run_id + " at step " + str(plan.step),
            )
        )
        if self.sessions is not None:
            snapshot = self.sessions.start(plan.session_id)
            steps.append(
                RecoveryStep(
                    action="restored session",
                    detail=snapshot.active_session_id
                    + (" (recovered)" if snapshot.recovered else " (new: the old one was gone)"),
                )
            )

        result = loop.run(plan.task, run_id=plan.run_id, resume=True)
        steps.append(
            RecoveryStep(
                action="continued the run",
                ok=getattr(result, "status", "") == "completed",
                detail="status " + str(getattr(result, "status", "")),
            )
        )
        return result, RecoveryReport(
            kind="program_restart",
            outcome="recovered" if getattr(result, "status", "") == "completed" else "failed",
            steps=steps,
            message="resumed " + plan.run_id,
            context={"run_id": plan.run_id, "task": plan.task, "status": getattr(result, "status", None)},
        )
