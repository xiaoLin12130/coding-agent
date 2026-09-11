"""AgentOrchestrator: bounded multi-agent collaboration (M7).

docs/runtime-agents.md fixes the shape:

    Planner -> Coder -> Reviewer -> 修复?
                                     |- yes -> Coder
                                     '- no  -> done

with StateKeeper, MemoryCurator and SafetyGuard as supporting roles, and four
hard constraints:

* no role bypasses the Executor — every role runs through an AgentLoop and so
  through the M4 SafetyLayer and the Executor
* no role writes shared state directly — Project State and Memory change only
  through their tools, which have their own validation and review
* bounded rounds, bounded steps per role, bounded wall-clock time
* no infinite agent conversation — a round that repeats the same verdict and
  the same issues stalls the collaboration instead of spinning
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..context.builder import ContextBuilder
from ..context.session import SessionManager
from ..tools import Executor, ToolContext, build_default_registry
from ..tools.registry import ToolRegistry
from .llm import ModelClient
from .loop import AgentLoop
from .models import (
    AgentEvent,
    LoopLimits,
    OrchestrationResult,
    OrchestrationStatus,
    ReviewVerdict,
    RoleRun,
    RoleSpec,
    RoundRecord,
)
from .roles import get_role, parse_review, parse_safety


class OrchestrationLimits(LoopLimits):
    """Loop limits plus the collaboration bounds."""

    max_rounds: int = 3
    stall_threshold: int = 2


def _default_limits() -> "OrchestrationLimits":
    return OrchestrationLimits()


class AgentOrchestrator:
    """Runs the roles for one task."""

    def __init__(
        self,
        model: ModelClient | None = None,
        sessions: SessionManager | None = None,
        context: ToolContext | None = None,
        builder: ContextBuilder | None = None,
        limits: "OrchestrationLimits | None" = None,
        registry: ToolRegistry | None = None,
        safety: Any = None,
        checkpoints: Any = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        confirm: Any = None,
        clock: Callable[[], float] = time.monotonic,
        log_path: Any = None,
        *,
        model_factory: Callable[[RoleSpec], ModelClient] | None = None,
    ) -> None:
        if sessions is None or context is None:
            raise ValueError("AgentOrchestrator needs a SessionManager and a ToolContext")
        if model is None and model_factory is None:
            raise ValueError("AgentOrchestrator needs a model or a model_factory")
        self.model = model
        # A deployment may route roles to different models (a stronger one for
        # the reviewer, for instance); tests use it to script each role
        # separately instead of sharing one fragile reply queue.
        self.model_factory = model_factory
        self.sessions = sessions
        self.context = context
        self.builder = builder or ContextBuilder(
            sessions.transcript, sessions.memory, sessions.store
        )
        self.limits = limits or _default_limits()
        self.registry = registry or build_default_registry(context)
        self.safety = safety
        self.checkpoints = checkpoints
        self.on_event = on_event
        self.confirm = confirm
        # The collaboration budget reads this clock; a test can supply a fake
        # one to prove the bound without waiting in real time.
        self.clock = clock
        # Every role writes to the same tool audit log as a single-agent run.
        self.log_path = log_path
        self.role_runs: list[RoleRun] = []
        # The collaboration's event stream, including what each role did.
        self.events: list[AgentEvent] = []

    # -- role plumbing -----------------------------------------------------

    def executor_for(self, role: RoleSpec) -> Executor:
        """An Executor restricted to the role's tools.

        The role gets a registry holding only what it may use, so a missing
        capability is a fact rather than a request the model could ignore.
        """
        scoped = self.registry.subset(role.allowed_tools)
        return Executor(
            scoped,
            self.context,
            log_path=self.log_path,
            safety=self.safety,
        )

    def model_for(self, role: RoleSpec) -> ModelClient:
        """The model this role runs on."""
        if self.model_factory is not None:
            return self.model_factory(role)
        assert self.model is not None  # guaranteed by __init__
        return self.model

    def loop_for(self, role: RoleSpec, round_index: int = 0) -> AgentLoop:
        limits = LoopLimits(
            max_steps=role.max_steps,
            timeout_ms=self.limits.timeout_ms,
            max_tool_retries=self.limits.max_tool_retries,
            max_parse_retries=self.limits.max_parse_retries,
            tool_retry_backoff_ms=self.limits.tool_retry_backoff_ms,
            repeat_threshold=self.limits.repeat_threshold,
            max_identical_replies=self.limits.max_identical_replies,
        )
        return AgentLoop(
            self.model_for(role),
            self.executor_for(role),
            self.sessions,
            builder=self.builder,
            limits=limits,
            checkpoints=self.checkpoints,
            safety=self.safety,
            system=role.system_prompt,
            on_event=self._role_event(role, round_index),
            confirm=self.confirm,
            working_dir=self.context.working_dir,
        )

    def _role_event(self, role: RoleSpec, round_index: int):
        """Tag a role's events with the role and keep them in the run record.

        Collecting them matters: without the roles' events the result would
        show that a role failed but not why.
        """

        def handler(event: AgentEvent) -> None:
            payload = event.model_copy(
                update={
                    "data": {
                        **event.data,
                        "role": role.name,
                        "round": round_index,
                    },
                    "message": "[" + role.name + "] " + event.message,
                }
            )
            self.events.append(payload)
            if self.on_event is not None:
                try:
                    self.on_event(payload)
                except Exception:  # pragma: no cover - an observer must not break a run
                    pass

        return handler

    # -- running one role --------------------------------------------------

    def run_role(
        self,
        role: RoleSpec,
        prompt: str,
        round_index: int = 0,
        run_id: str | None = None,
    ) -> tuple[RoleRun, Any]:
        loop = self.loop_for(role, round_index)
        result = loop.run(prompt, run_id=run_id)
        record = RoleRun(
            role=role.name,
            round=round_index,
            status=result.status,
            message=result.final_message or result.reason,
            tool_calls=result.tool_calls,
            tool_failures=result.tool_failures,
            duration_ms=result.duration_ms,
            tools_used=sorted(result.tool_summary()),
        )
        if role.verdict_kind == "review":
            verdict, issues, _notes = parse_review(result.final_message)
            record.verdict = verdict
            record.issues = issues
        elif role.verdict_kind == "safety":
            verdict, issues, _notes = parse_safety(result.final_message)
            record.verdict = verdict
            record.issues = issues
        self.role_runs.append(record)
        return record, result

    # -- the collaboration -------------------------------------------------

    def run(self, task: str, run_id: str | None = None) -> OrchestrationResult:
        started = self.clock()
        started_at = datetime.now(timezone.utc)
        run_id = run_id or uuid.uuid4().hex[:12]
        deadline = started + self.limits.timeout_ms / 1000
        self.events = []
        events = self.events

        self.sessions.start()
        self.sessions.record("user", task)

        def emit(
            type_: str,
            message: str,
            round_index: int = 0,
            data: dict | None = None,
            ok: bool | None = None,
        ):
            event = AgentEvent(
                type=type_,  # type: ignore[arg-type]
                step=round_index,
                message=message,
                ok=ok,
                data=data or {},
            )
            events.append(event)
            if self.on_event is not None:
                try:
                    self.on_event(event)
                except Exception:  # pragma: no cover - an observer must not break a run
                    pass
            return event

        emit("run_start", "task: " + task[:200])

        # --- 1. Planner ---------------------------------------------------
        planner = get_role("planner")
        plan_run, _plan_result = self.run_role(planner, task, run_id=run_id + "-plan")
        emit(
            "model_reply",
            "[planner] " + plan_run.message[:200],
            data={"role": "planner"},
        )
        if plan_run.status not in ("completed", "max_steps"):
            return self._finish(
                run_id, task, "error",
                "the planner could not produce a plan: " + plan_run.status,
                "", [], started, started_at, events,
            )
        plan = plan_run.message.strip() or task

        # --- 2. SafetyGuard reviews the plan ------------------------------
        guard = get_role("safety_guard")
        guard_run, _ = self.run_role(
            guard,
            "Review this plan for overreach before it is executed:\n\n"
            + plan
            + "\n\nTask: "
            + task,
            run_id=run_id + "-guard",
        )
        if guard_run.verdict == "blocked":
            emit("blocked", "[safety_guard] " + "; ".join(guard_run.issues[:3]))
            return self._finish(
                run_id, task, "blocked",
                "the safety guard blocked the plan: "
                + ("; ".join(guard_run.issues[:2]) or "no reason given"),
                plan, [], started, started_at, events,
            )

        # --- 3. Coder/Reviewer rounds -------------------------------------
        rounds: list[RoundRecord] = []
        status: OrchestrationStatus = "max_rounds"
        reason = "reached the round limit without approval"
        feedback: list[str] = []
        final_message = ""
        last_signature: tuple[str, tuple[str, ...]] | None = None
        stalls = 0

        for index in range(1, self.limits.max_rounds + 1):
            if self.clock() >= deadline:
                status, reason = "timeout", "the collaboration exceeded its time budget"
                break

            round_started = self.clock()
            record = RoundRecord(index=index)

            coder_prompt = (
                "Task: " + task + "\n\nPlan:\n" + plan
                + (
                    "\n\nThe reviewer rejected the previous attempt. Fix exactly "
                    "these issues:\n- " + "\n- ".join(feedback)
                    if feedback
                    else ""
                )
            )
            coder_run, coder_result = self.run_role(
                get_role("coder"), coder_prompt, round_index=index, run_id=f"{run_id}-c{index}"
            )
            record.coder = coder_run
            emit(
                "model_reply",
                "[coder] " + coder_run.message[:200],
                round_index=index,
                data={"role": "coder"},
            )
            if coder_run.status not in ("completed", "max_steps"):
                record.verdict = "needs_fix"
                record.duration_ms = int((self.clock() - round_started) * 1000)
                rounds.append(record)
                status, reason = "error", "the coder run ended with " + coder_run.status
                break

            reviewer_prompt = (
                "Task: " + task + "\n\nPlan:\n" + plan
                + "\n\nThe coder reports:\n" + coder_run.message[:1500]
                + "\n\nVerify the work independently and give your verdict."
            )
            reviewer_run, _ = self.run_role(
                get_role("reviewer"),
                reviewer_prompt,
                round_index=index,
                run_id=f"{run_id}-r{index}",
            )
            record.reviewer = reviewer_run
            record.verdict = (reviewer_run.verdict or "unknown")  # type: ignore[assignment]
            record.issues = list(reviewer_run.issues)
            record.duration_ms = int((self.clock() - round_started) * 1000)
            rounds.append(record)
            emit(
                "model_reply",
                "[reviewer] " + (reviewer_run.verdict or "unknown")
                + (" — " + "; ".join(reviewer_run.issues[:2]) if reviewer_run.issues else ""),
                round_index=index,
                ok=reviewer_run.verdict == "approved",
                data={"role": "reviewer", "verdict": reviewer_run.verdict},
            )

            if reviewer_run.verdict == "approved":
                status, reason = "completed", "the reviewer approved the work"
                final_message = reviewer_run.message
                break

            # stalled when the reviewer repeats itself with nothing new
            signature = (str(reviewer_run.verdict), tuple(sorted(reviewer_run.issues)))
            if signature == last_signature:
                stalls += 1
            else:
                stalls = 1
                last_signature = signature
            if stalls >= self.limits.stall_threshold:
                status = "stalled"
                reason = (
                    "the reviewer repeated the same issues with no progress: "
                    + "; ".join(reviewer_run.issues[:2] or ["no issues given"])
                )
                emit("loop_detected", reason, round_index=index)
                break

            feedback = list(reviewer_run.issues) or [
                "the reviewer did not state a verdict; verify the task and report it"
            ]

        # --- 4. supporting roles ------------------------------------------
        summary = self._summary_of(rounds, status, reason)
        self.run_role(
            get_role("state_keeper"),
            "Task: " + task + "\n\nOutcome: " + summary,
            run_id=run_id + "-state",
        )
        self.run_role(
            get_role("memory_curator"),
            "Task: " + task + "\n\nWhat happened:\n" + summary,
            run_id=run_id + "-memory",
        )

        return self._finish(
            run_id, task, status, reason, plan, rounds, started, started_at, events,
            final_message=final_message,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _summary_of(rounds: list[RoundRecord], status: str, reason: str) -> str:
        lines = ["status: " + status, "reason: " + reason]
        for record in rounds:
            coder = record.coder.message[:200] if record.coder else "(no coder run)"
            lines.append(
                "round "
                + str(record.index)
                + ": coder="
                + (record.coder.status if record.coder else "?")
                + " reviewer="
                + record.verdict
                + " issues="
                + ("; ".join(record.issues[:3]) or "none")
            )
            lines.append("  coder said: " + coder)
        return "\n".join(lines)

    def _finish(
        self,
        run_id: str,
        task: str,
        status: OrchestrationStatus,
        reason: str,
        plan: str,
        rounds: list[RoundRecord],
        started: float,
        started_at: datetime,
        events: list[AgentEvent],
        final_message: str = "",
    ) -> OrchestrationResult:
        finished_at = datetime.now(timezone.utc)
        events.append(
            AgentEvent(
                type="run_end",
                step=len(rounds),
                message=status + ": " + reason,
                ok=status == "completed",
            )
        )
        if self.on_event is not None:
            try:
                self.on_event(events[-1])
            except Exception:  # pragma: no cover
                pass

        tool_calls = sum(run.tool_calls for run in self.role_runs)
        tool_failures = sum(run.tool_failures for run in self.role_runs)
        return OrchestrationResult(
            run_id=run_id,
            task=task,
            status=status,
            reason=reason,
            plan=plan,
            rounds=rounds,
            role_runs=list(self.role_runs),
            round_count=len(rounds),
            tool_calls=tool_calls,
            tool_failures=tool_failures,
            duration_ms=int((self.clock() - started) * 1000),
            final_message=final_message,
            started_at=started_at,
            finished_at=finished_at,
            events=events,
        )