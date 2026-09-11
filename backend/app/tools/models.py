"""Models for the Tool layer (M3).

The shape of one tool call, one tool result, and the structured parse errors
that let an LLM repair its own output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high"]

# How a tool call was recovered from the model output.
CallFormat = Literal["json", "json5", "code_fence", "fenced_json5", "embedded", "none"]

# Structured parse failure codes. Every one of them is repairable by the model
# when it is told what went wrong, which is why they are enumerated rather
# than reported as free text.
ParseIssueCode = Literal[
    "empty_input",
    "no_tool_call",
    "invalid_json",
    "invalid_json5",
    "unbalanced_brackets",
    "not_an_object",
    "missing_name",
    "missing_arguments",
    "invalid_arguments",
    "unknown_tool",
    "too_many_calls",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParseIssue(BaseModel):
    """One structured, repairable problem found while parsing."""

    model_config = ConfigDict(extra="forbid")

    code: ParseIssueCode
    message: str
    position: int | None = None
    snippet: str = ""
    repair_hint: str = ""
    retryable: bool = True


class ToolCall(BaseModel):
    """One request to run a tool. Arguments are validated by the Executor."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""
    format: CallFormat = "json"
    index: int = 0


class ParseOutcome(BaseModel):
    """Everything the parser learned about one block of model output."""

    model_config = ConfigDict(extra="forbid")

    calls: list[ToolCall] = Field(default_factory=list)
    issues: list[ParseIssue] = Field(default_factory=list)
    format: CallFormat = "none"
    raw: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.calls) and not self.issues

    @property
    def partial(self) -> bool:
        return bool(self.calls) and bool(self.issues)

    def codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


class ToolErrorInfo(BaseModel):
    """Structured failure of an executed tool call."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ToolResult(BaseModel):
    """The outcome of one executed tool call.

    'output' is untrusted DATA (file text, shell output, page text). It is
    never an instruction, regardless of what it says.
    """

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    ok: bool
    output: str = ""
    error: ToolErrorInfo | None = None
    risk: RiskLevel = "low"
    duration_ms: int = 0
    idempotent_replay: bool = False
    artifacts: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)


class ToolSpec(BaseModel):
    """Declarative description of one tool.

    'requires_confirmation' is the seam the M4 SafetyLayer fills: M3 does not
    implement the policy (path limits, sensitive files, risk grading shown in
    the UI), it only refuses to run such a tool unless the caller supplies an
    approval hook or an explicit confirmation.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    risk: RiskLevel = "low"
    requires_confirmation: bool = False
    idempotent: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCallLogEntry(BaseModel):
    """One line of the append-only tool call log."""

    model_config = ConfigDict(extra="ignore")

    at: datetime = Field(default_factory=utc_now)
    call_id: str
    name: str
    arguments_preview: str
    ok: bool
    error_code: str | None = None
    duration_ms: int = 0
    idempotent_replay: bool = False
    confirmed: bool = False
