"""Session recovery: the documented Context-full sequence.

docs/M6:

    完成当前 turn -> 保存 State -> 摘要 Transcript -> 新建 Session -> 恢复任务

The M2 SessionManager already performs the mechanics (summarise, archive, open,
seed). This unit sequences them for a running task and verifies what actually
landed in the new session, so "the task continues" is checked rather than
assumed:

* Project State injection
* Memory injection
* Recent Transcript injection
* the current task
"""

from __future__ import annotations

from ..context.builder import ContextBuilder, render_project_state
from ..context.session import ROTATION_REASON_BUDGET, SessionManager
from ..models import ProjectState
from .models import (
    ContextPressure,
    RecoveryReport,
    RecoveryStep,
)
from .thresholds import ContextPressurePolicy


class SessionRecovery:
    def __init__(
        self,
        sessions: SessionManager,
        builder: ContextBuilder | None = None,
        policy: ContextPressurePolicy | None = None,
    ) -> None:
        self.sessions = sessions
        self.builder = builder or ContextBuilder(
            sessions.transcript, sessions.memory, sessions.store
        )
        self.policy = policy or ContextPressurePolicy()

    # -- pressure ----------------------------------------------------------

    def evaluate(
        self,
        session_id: str,
        system: str,
        task: str,
        tool_results: list[str] | None = None,
    ) -> ContextPressure:
        context = self.builder.build(
            session_id=session_id, system=system, task=task, tool_results=tool_results
        )
        return self.policy.evaluate(context, self.builder.budget.max_chars)

    # -- the sequence ------------------------------------------------------

    def rotate(
        self,
        reason: str = ROTATION_REASON_BUDGET,
        project_state: ProjectState | None = None,
        title: str = "",
    ) -> RecoveryReport:
        """Archive the active session and continue in a seeded one."""
        steps: list[RecoveryStep] = []

        # 1. the turn is over (the caller only rotates at a step boundary) and
        #    the project state is on disk; make the saved copy explicit.
        state = project_state or self.sessions.store.load_project_state()
        if project_state is not None:
            self.sessions.save_project_state(state)
            steps.append(RecoveryStep(action="saved project state"))
        else:
            steps.append(RecoveryStep(action="project state already on disk"))

        # 2-4. summarise, archive, open the new session, seed it.
        rotation = self.sessions.rotate(reason=reason, project_state=state, title=title)
        steps.append(
            RecoveryStep(
                action="summarised transcript",
                detail=str(rotation.summary.summarized_count) + " message(s)",
            )
        )
        steps.append(
            RecoveryStep(
                action="archived session",
                detail=rotation.archived_session_id,
            )
        )
        steps.append(
            RecoveryStep(action="opened session", detail=rotation.new_session_id)
        )

        # 5. verify the injections the task needs to continue.
        injections = self.injections(rotation.new_session_id, task=state.current_task or "")
        for name, present in injections.items():
            steps.append(
                RecoveryStep(
                    action="injected " + name,
                    ok=present,
                    detail="" if present else "MISSING from the seed",
                )
            )

        ok = all(injections.values())
        return RecoveryReport(
            kind="context_hard",
            outcome="recovered" if ok else "failed",
            steps=steps,
            message=(
                "continuing in " + rotation.new_session_id
                if ok
                else "the new session is missing part of the seed"
            ),
            context={
                "archived_session_id": rotation.archived_session_id,
                "new_session_id": rotation.new_session_id,
                "carried_entry_indices": rotation.carried_entry_indices,
                "seed_entry_index": rotation.seed_entry_index,
                "injections": injections,
                "summary_chars": len(rotation.summary.text),
            },
        )

    def injections(self, session_id: str, task: str = "") -> dict[str, bool]:
        """What a session seed actually contains.

        Each item is satisfied when the seed carries the data OR when there was
        nothing to carry: rotating an empty session is not a failure, and
        reporting it as one would train the caller to ignore the check.
        """
        entries = self.sessions.transcript.read(session_id)
        seeds = [e for e in entries if e.meta.get("kind") == "session_seed"]
        seed = "\n".join(entry.content for entry in seeds)
        carried = [entry for entry in entries if entry.meta.get("carried_from")]
        rotated_from = seeds[0].meta.get("rotated_from") if seeds else None

        state = self.sessions.store.load_project_state()
        state_needed = bool(render_project_state(state))
        state_present = "## Project state" in seed

        memory_needed = self.sessions.memory.count() > 0
        memory_present = "## Remembered facts" in seed

        old_entries = (
            self.sessions.transcript.read(str(rotated_from)) if rotated_from else []
        )
        transcript_needed = bool(self.sessions.transcript.split_turns(old_entries))
        transcript_present = bool(carried) or (
            "## Summary of the archived transcript" in seed
        )

        task_needed = bool(task)
        task_present = ("## Current task" in seed) and (task in seed if task else True)

        return {
            "project state": state_present or not state_needed,
            "memory": memory_present or not memory_needed,
            "recent transcript": transcript_present or not transcript_needed,
            "current task": task_present or not task_needed,
        }

    # -- soft pressure -----------------------------------------------------

    def apply_soft(self, default_recent_turns: int) -> RecoveryReport:
        """Carry less without losing the session.

        The builder already drops low-priority sections; the extra step at the
        soft threshold is to keep fewer recent turns, which is the largest
        section in a long session.
        """
        reduced = self.policy.recent_turns_for("soft", default_recent_turns)
        previous = self.builder.recent_turns
        self.builder.recent_turns = reduced
        return RecoveryReport(
            kind="context_soft",
            outcome="recovered" if reduced < previous else "not_needed",
            steps=[
                RecoveryStep(
                    action="reduced recent turns",
                    detail=str(previous) + " -> " + str(reduced),
                )
            ],
            message="context is filling up; carrying fewer recent turns",
            context={"recent_turns": reduced, "previous": previous},
        )
