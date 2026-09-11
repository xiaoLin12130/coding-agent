"""Agent evaluation (M9): the six dimensions, run for real.

Every scenario runs through the REAL components — the AgentLoop, the
ToolCallParser, the SafetyLayer, the Executor and the SessionManager — inside a
throwaway workspace. Nothing is mocked except the model, which is scripted (and,
for the recovery cases, deliberately broken first).

What the dimensions mean here:

* tool_selection    the model picks the tools the task needs, and no others
* tool_parsing      messy packaging (fence, JSON5, prose) still executes
* task_completion   the task's RESULT is correct on disk, not just "status ok"
* recovery          a failing model end and a crashed run both continue
* safety            a dangerous or unconfirmed call changes nothing
* context_switching rotation happens at the threshold and the task continues
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ..agents.checkpoint import CheckpointStore
from ..agents.llm import ModelClientError, ScriptedModel
from ..agents.loop import DEFAULT_SYSTEM, AgentLoop
from ..agents.models import LoopLimits
from ..config import AppPaths
from ..context import ContextBuilder, SessionManager
from ..recovery.models import ContextThresholds
from ..storage import StateStore
from ..tools import Executor, ToolContext, build_default_registry
from .dataset import load_agent_cases
from .models import (
    DIMENSIONS,
    AgentCase,
    AgentCaseResult,
    AgentReport,
    CheckResult,
    DimensionScore,
)

TIMEOUT_MS = 120_000


class FlakyModel(ScriptedModel):
    """A scripted model that fails its first N calls (fault injection)."""

    def __init__(self, replies: list[str], fail_first: int = 0, **kwargs) -> None:
        super().__init__(replies, **kwargs)
        self.remaining_failures = fail_first
        self.failures = 0

    def complete(self, prompt: str, system: str | None = None):
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            self.failures += 1
            self.calls.append(prompt)
            raise ModelClientError(
                "evaluation fault injection: the model end is unavailable"
            )
        return super().complete(prompt, system)


class _Env:
    """One throwaway workspace with the real execution stack."""

    def __init__(self, case: AgentCase, base: Path) -> None:
        self.case = case
        self.base = base
        self.project = base / "project"
        self.project.mkdir(parents=True, exist_ok=True)
        for name, content in case.workspace.items():
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for name, content in case.outside_files.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        paths = AppPaths(
            project_root=self.project,
            state_dir=self.project,
            project_state_file=self.project / "project_state.json",
            memory_file=self.project / "memory.json",
        )
        self.paths = paths
        self.store = StateStore(paths)
        self.context = ToolContext(working_dir=self.project, store=self.store)
        self.executor = Executor(
            build_default_registry(self.context),
            self.context,
            log_path=self.project / "runs" / "tool-calls.jsonl",
        )
        self.sessions = SessionManager(self.project / "state" / "sessions", store=self.store)
        self.builder = ContextBuilder(
            self.sessions.transcript, self.sessions.memory, self.sessions.store
        )
        self.checkpoints = CheckpointStore(self.project / "state" / "checkpoints")

    def loop(self, model, thresholds: ContextThresholds | None, restore_model_state: bool = True):
        case = self.case
        confirm = None
        if case.confirm == "once":
            confirm = lambda request: "once"  # noqa: E731 - a fixed answer
        elif case.confirm == "reject":
            confirm = lambda request: "reject"  # noqa: E731
        return AgentLoop(
            model,
            self.executor,
            self.sessions,
            builder=self.builder,
            limits=LoopLimits(
                max_steps=case.max_steps,
                timeout_ms=TIMEOUT_MS,
                max_tool_retries=case.max_tool_retries,
                max_parse_retries=case.max_parse_retries,
            ),
            checkpoints=self.checkpoints,
            system=DEFAULT_SYSTEM,
            confirm=confirm,
            working_dir=self.project,
            thresholds=thresholds,
            on_model_failure=(lambda exc: True) if case.recover_model else None,
            restore_model_state=restore_model_state,
        )


def _thresholds(case: AgentCase) -> ContextThresholds | None:
    if case.soft_ratio is None and case.hard_ratio is None:
        return None
    values: dict[str, float] = {}
    if case.soft_ratio is not None:
        values["soft_ratio"] = case.soft_ratio
    if case.hard_ratio is not None:
        values["hard_ratio"] = case.hard_ratio
    soft = values.get("soft_ratio")
    hard = values.get("hard_ratio")
    if soft is not None and hard is not None and soft > hard:
        raise ValueError("case " + case.id + ": soft_ratio must not exceed hard_ratio")
    return ContextThresholds(**values)


def _run(case: AgentCase, env: _Env):
    """Run the scenario; returns the result of the last (or only) loop run."""
    thresholds = _thresholds(case)
    model = FlakyModel(
        list(case.replies), fail_first=case.fail_first_calls, final_message=case.final_message
    )
    if case.resume_after_steps is None:
        return env.loop(model, thresholds).run(case.task), model

    # Recovery: stop after N steps and continue from the checkpoint, exactly as
    # the CLI does after a crash.
    first_case = case.model_copy(update={"max_steps": case.resume_after_steps})
    original = env.case
    env.case = first_case
    try:
        first = env.loop(model, thresholds).run(case.task)
    finally:
        env.case = original
    if first.status == "completed":
        return first, model
    resumed = env.loop(model, thresholds, restore_model_state=False).run(
        case.task, run_id=first.run_id, resume=True
    )
    return _Resumed(resumed, first), model


class _Resumed:
    """The resumed run, remembering the interrupted one."""

    def __init__(self, result, first) -> None:
        self._result = result
        self.first = first

    def __getattr__(self, item: str):
        return getattr(self._result, item)


def run_agent_case(case: AgentCase, workdir: Path | str | None = None) -> AgentCaseResult:
    """Run one scenario and check it against its contract."""
    started = time.monotonic()
    base = Path(workdir) if workdir is not None else Path(
        tempfile.mkdtemp(prefix="eval-" + case.id + "-")
    )
    temporary = workdir is None
    checks: list[CheckResult] = []
    observed: dict = {}
    error = ""
    try:
        env = _Env(case, base)
        result, model = _run(case, env)
        observed = _observe(case, env, result, model)
        checks = _check(case.expect, observed, env)
    except Exception as exc:  # noqa: BLE001 - a broken case is a failed case
        error = type(exc).__name__ + ": " + str(exc)
    finally:
        if temporary:
            shutil.rmtree(base, ignore_errors=True)

    passed = not error and all(check.ok for check in checks)
    return AgentCaseResult(
        id=case.id,
        dimension=case.dimension,
        passed=passed,
        checks=checks,
        observed=observed,
        error=error,
        known_gap=case.known_gap,
        duration_ms=int((time.monotonic() - started) * 1000),
        explanation=case.explanation,
    )


def _observe(case: AgentCase, env: _Env, result, model) -> dict:
    events = list(getattr(result, "events", []))
    sessions = list(env.sessions.sessions())
    active = env.sessions.current_session_id()
    transcript_roles = [entry.role for entry in env.sessions.transcript.read(active)] if active else []
    observed = {
        "status": getattr(result, "status", ""),
        "reason": getattr(result, "reason", ""),
        "tools_used": list(getattr(result, "tool_summary", lambda: {})()),
        "tool_calls": getattr(result, "tool_calls", 0),
        "tool_failures": getattr(result, "tool_failures", 0),
        "steps": getattr(result, "step_count", 0),
        "final_message": getattr(result, "final_message", ""),
        "event_types": sorted({event.type for event in events}),
        "parse_failures": len(
            [step for step in getattr(result, "steps", []) if step.parse_issues]
        ),
        "files": {
            name: (env.project / name).read_text(encoding="utf-8")
            if (env.project / name).exists()
            else None
            for name in case.expect.files
        },
        "absent": {name: not (env.project / name).exists() for name in case.expect.files_absent},
        "transcript_roles": transcript_roles,
        "session_count": len(sessions),
        "tool_results": [event.message for event in events if event.type == "tool_result"],
        "run_text": "\n".join(
            [event.message for event in events]
            + [
                getattr(entry, "content", "")
                for entry in env.sessions.transcript.read(active)
            ]
            if active
            else [event.message for event in events]
        ),
    }
    if case.resume_after_steps is not None:
        observed["first_status"] = getattr(getattr(result, "first", None), "status", "")
    return observed


def _check(expect, observed: dict, env: _Env) -> list[CheckResult]:
    checks: list[CheckResult] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append(CheckResult(name=name, ok=ok, detail=detail))

    if expect.status:
        record(
            "status",
            observed["status"] == expect.status,
            "expected '" + expect.status + "', got '" + observed["status"] + "'"
            + ((" (" + observed["reason"] + ")") if observed["reason"] else ""),
        )
    if expect.tools_used:
        record(
            "tools_used",
            observed["tools_used"] == expect.tools_used,
            "expected " + str(expect.tools_used) + ", got " + str(observed["tools_used"]),
        )
    for name in expect.tools_forbidden:
        record(
            "tool_not_used:" + name,
            name not in observed["tools_used"],
            "the run used " + name,
        )
    if expect.min_tool_calls is not None:
        record(
            "min_tool_calls",
            observed["tool_calls"] >= expect.min_tool_calls,
            "expected at least "
            + str(expect.min_tool_calls)
            + ", got "
            + str(observed["tool_calls"]),
        )
    if expect.max_tool_failures is not None:
        record(
            "max_tool_failures",
            observed["tool_failures"] <= expect.max_tool_failures,
            "expected at most "
            + str(expect.max_tool_failures)
            + ", got "
            + str(observed["tool_failures"]),
        )
    if expect.min_tool_failures is not None:
        record(
            "min_tool_failures",
            observed["tool_failures"] >= expect.min_tool_failures,
            "expected at least "
            + str(expect.min_tool_failures)
            + ", got "
            + str(observed["tool_failures"]),
        )
    for name, content in expect.files.items():
        actual = observed["files"].get(name)
        record(
            "file:" + name,
            actual == content,
            "content differs"
            if actual != content
            else "",
        )
    for name in expect.files_absent:
        record("file_absent:" + name, observed["absent"].get(name, False), "the file exists")
    for fragment in expect.final_message_contains:
        record(
            "final_message_contains:" + fragment,
            fragment in observed["final_message"],
            "final message was: " + observed["final_message"][:120],
        )
    for event_type in expect.event_types:
        record(
            "event:" + event_type,
            event_type in observed["event_types"],
            "events were: " + ", ".join(observed["event_types"]),
        )
    if expect.transcript_roles:
        record(
            "transcript_roles",
            observed["transcript_roles"] == expect.transcript_roles,
            "expected "
            + str(expect.transcript_roles)
            + ", got "
            + str(observed["transcript_roles"]),
        )
    if expect.parse_failures is not None:
        record(
            "parse_failures",
            observed["parse_failures"] == expect.parse_failures,
            "expected "
            + str(expect.parse_failures)
            + " step(s) with parse issues, got "
            + str(observed["parse_failures"]),
        )
    if expect.context_rotated is not None:
        rotated = "context_rotated" in observed["event_types"]
        record(
            "context_rotated",
            rotated == expect.context_rotated,
            "expected context_rotated=" + str(expect.context_rotated),
        )
    for fragment in expect.tool_results_contain:
        record(
            "tool_result_contains:" + fragment,
            any(fragment in text for text in observed["tool_results"]),
            "tool results were: " + " | ".join(observed["tool_results"])[:200],
        )
    for fragment in expect.never_in_output:
        record(
            "never_in_output:" + fragment,
            fragment not in observed["run_text"],
            "the value reached the run's output",
        )
    if expect.resume_completed is not None:
        record(
            "resume_completed",
            observed["status"] == "completed" and observed.get("first_status") != "completed",
            "first run ended '"
            + str(observed.get("first_status"))
            + "', resumed run ended '"
            + observed["status"]
            + "'",
        )
    return checks


def evaluate_agent(cases: list[AgentCase] | None = None) -> AgentReport:
    """Run every scenario and score the six dimensions."""
    started = time.monotonic()
    selected = cases if cases is not None else load_agent_cases()
    results = [run_agent_case(case) for case in selected]

    grouped: dict[str, list[AgentCaseResult]] = {}
    for result in results:
        grouped.setdefault(result.dimension, []).append(result)
    scores = [
        DimensionScore(
            dimension=dimension,
            total=len(items),
            passed=sum(1 for item in items if item.passed),
            rate=sum(1 for item in items if item.passed) / len(items),
        )
        for dimension, items in sorted(grouped.items(), key=lambda item: _order(item[0]))
    ]
    passed = sum(1 for result in results if result.passed)
    return AgentReport(
        total=len(results),
        passed=passed,
        pass_rate=(passed / len(results)) if results else 0.0,
        by_dimension=scores,
        results=results,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _order(dimension: str) -> int:
    return DIMENSIONS.index(dimension) if dimension in DIMENSIONS else len(DIMENSIONS)
