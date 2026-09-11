"""Models for the Agent Runtime loop (M5).

The loop itself is model-agnostic: it drives a ModelClient (a web LLM through
the M1 browser provider, or a scripted model in tests), and every tool call it
issues goes through the M3 parser, the M4 SafetyLayer and the Executor. The
AgentLoop never touches a file or a shell itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# How a run ended.
#
# completed   the model stopped asking for tools and produced a final answer
# max_steps   the step budget ran out
# timeout     the run deadline passed
# interrupted the user stopped it
# blocked     the SafetyLayer denied a call and the model could not continue
# loop        the same call repeated past the detection threshold
# error       an unrecoverable failure (e.g. the model could not be reached)
RunStatus = Literal[
    "completed", "max_steps", "timeout", "interrupted", "blocked", "loop", "error"
]

EventType = Literal[
    "run_start",
    "step_start",
    "model_request",
    "model_reply",
    "parse_failed",
    "tool_start",
    "tool_retry",
    "tool_result",
    "blocked",
    "checkpoint",
    "loop_detected",
    "context_pressure",
    "context_rotated",
    "model_recovered",
    "run_end",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LoopLimits(BaseModel):
    """Every bound the loop must respect (docs/runtime-agents.md)."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=25, ge=1)
    timeout_ms: int = Field(default=600_000, gt=0)
    # Retry a tool call whose error the Executor marked retryable.
    max_tool_retries: int = Field(default=2, ge=0)
    tool_retry_backoff_ms: int = Field(default=250, ge=0)
    # Ask the model again when its output cannot be parsed (M3's policy).
    max_parse_retries: int = Field(default=2, ge=0)
    # Loop detection: the same call this many times in a row ends the run.
    repeat_threshold: int = Field(default=3, ge=2)
    # Stop early when the model repeats the same reply without a tool call.
    max_identical_replies: int = Field(default=2, ge=2)


class AgentEvent(BaseModel):
    """One observable moment in a run (feeds logs, the console and the CLI)."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    step: int = 0
    at: datetime = Field(default_factory=utc_now)
    message: str = ""
    tool: str | None = None
    ok: bool | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def render(self) -> str:
        prefix = "step " + str(self.step) + " " if self.step else ""
        suffix = ""
        if self.tool:
            suffix = " [" + self.tool + "]"
        return prefix + self.type + suffix + (": " + self.message if self.message else "")


class ToolAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    ok: bool
    error_code: str | None = None
    duration_ms: int = 0
    retried: bool = False


class StepRecord(BaseModel):
    """What happened in one loop step."""

    model_config = ConfigDict(extra="forbid")

    index: int
    model_output: str = ""
    calls: list[str] = Field(default_factory=list)
    tool_attempts: dict[str, list[ToolAttempt]] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)
    parse_issues: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    note: str = ""


class AgentRunResult(BaseModel):
    """The outcome of one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    final_message: str = ""
    steps: list[StepRecord] = Field(default_factory=list)
    step_count: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    duration_ms: int = 0
    reason: str = ""
    checkpoint_path: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    events: list[AgentEvent] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def tool_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for step in self.steps:
            for name in step.calls:
                summary[name] = summary.get(name, 0) + 1
        return summary


class Checkpoint(BaseModel):
    """Durable state of a run, written after every step."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task: str
    system: str
    session_id: str
    step: int = 0
    status: RunStatus | None = None
    model_state: dict[str, Any] = Field(default_factory=dict)
    tool_calls: int = 0
    tool_failures: int = 0
    last_message: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Multi-agent orchestration (M7)
# ---------------------------------------------------------------------------

RoleName = Literal[
    "planner",
    "coder",
    "reviewer",
    "memory_curator",
    "state_keeper",
    "safety_guard",
]

# The Reviewer's answer, and the SafetyGuard's.
ReviewVerdict = Literal["approved", "needs_fix", "unknown"]
SafetyVerdict = Literal["safe", "blocked", "unknown"]

OrchestrationStatus = Literal[
    "completed", "max_rounds", "timeout", "blocked", "stalled", "error"
]


class RoleSpec(BaseModel):
    """One runtime role: what it may do, and what it is told to do."""

    model_config = ConfigDict(extra="forbid")

    name: RoleName
    purpose: str
    system_prompt: str
    # The tool names this role may use. Enforced by giving the role a registry
    # holding only these, never by asking the model to behave.
    allowed_tools: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=6, ge=1)
    # Whether the role's final message is a structured verdict.
    verdict_kind: Literal["review", "safety", "none"] = "none"


class RoleRun(BaseModel):
    """What one role invocation did."""

    model_config = ConfigDict(extra="forbid")

    role: RoleName
    round: int = 0
    status: str = ""
    message: str = ""
    tool_calls: int = 0
    tool_failures: int = 0
    duration_ms: int = 0
    verdict: str | None = None
    issues: list[str] = Field(default_factory=list)
    # Only the tool NAMES reach the orchestrator's record: argument values can
    # carry secrets, and the transcript already holds what happened.
    tools_used: list[str] = Field(default_factory=list)

    def render(self) -> str:
        head = self.role + " (round " + str(self.round) + "): " + self.status
        if self.verdict:
            head += " -> " + self.verdict
        if self.issues:
            head += " (" + str(len(self.issues)) + " issue(s))"
        return head


class RoundRecord(BaseModel):
    """One Planner/Coder/Reviewer round."""

    model_config = ConfigDict(extra="forbid")

    index: int
    coder: RoleRun | None = None
    reviewer: RoleRun | None = None
    safety: RoleRun | None = None
    verdict: ReviewVerdict = "unknown"
    issues: list[str] = Field(default_factory=list)
    duration_ms: int = 0


class OrchestrationResult(BaseModel):
    """The outcome of a multi-agent collaboration."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task: str
    status: OrchestrationStatus
    reason: str = ""
    plan: str = ""
    rounds: list[RoundRecord] = Field(default_factory=list)
    role_runs: list[RoleRun] = Field(default_factory=list)
    round_count: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    duration_ms: int = 0
    final_message: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    events: list[AgentEvent] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def role_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for run in self.role_runs:
            summary[run.role] = summary.get(run.role, 0) + 1
        return summary

    def tools_by_role(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for run in self.role_runs:
            result.setdefault(run.role, []).extend(run.tools_used)
        return result


class ModelReply(BaseModel):
    """One model response, tagged with where it came from."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: str = "model"
    duration_ms: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
