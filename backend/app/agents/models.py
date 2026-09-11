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


class ModelReply(BaseModel):
    """One model response, tagged with where it came from."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: str = "model"
    duration_ms: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
