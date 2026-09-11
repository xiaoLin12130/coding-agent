"""Models for the Safety layer (M4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high"]

# The three buttons docs/safety.md requires.
ConfirmationChoice = Literal["reject", "once", "session"]

# allow  -> the call may run
# confirm-> a human must approve it first
# deny   -> it must never run
SafetyDecision = Literal["allow", "confirm", "deny"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PathDecision(BaseModel):
    """Verdict of the filesystem policy for one path."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str
    requested: str
    resolved: str | None = None
    inside_project: bool = False
    sensitive: str | None = None


class ShellAssessment(BaseModel):
    """Risk grading of one shell command."""

    model_config = ConfigDict(extra="forbid")

    risk: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    deny: bool = False
    deny_reason: str = ""
    outside_paths: list[str] = Field(default_factory=list)
    sensitive_reference: str | None = None


class InjectionFinding(BaseModel):
    """One instruction-like pattern found in untrusted content."""

    model_config = ConfigDict(extra="forbid")

    category: str
    message: str
    excerpt: str = ""
    position: int = 0


class ConfirmationRequest(BaseModel):
    """Exactly what the human must see before a risky call runs.

    docs/safety.md fixes the four facts: command, cwd, impact scope, risk.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    risk: RiskLevel
    command: str = ""
    cwd: str = ""
    impact: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    choices: list[ConfirmationChoice] = Field(
        default_factory=lambda: ["reject", "once", "session"]
    )
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None

    def summary(self) -> str:
        lines = [
            "tool    : " + self.tool,
            "risk    : " + self.risk.upper(),
        ]
        if self.command:
            lines.append("command : " + self.command)
        if self.cwd:
            lines.append("cwd     : " + self.cwd)
        if self.impact:
            lines.append("impact  : " + "; ".join(self.impact))
        if self.reasons:
            lines.append("why     : " + "; ".join(self.reasons))
        lines.append("choices : " + " / ".join(self.choices))
        return "\n".join(lines)


class SafetyVerdict(BaseModel):
    """What the SafetyLayer decided about one tool call."""

    model_config = ConfigDict(extra="forbid")

    decision: SafetyDecision
    risk: RiskLevel = "low"
    reasons: list[str] = Field(default_factory=list)
    confirmation: ConfirmationRequest | None = None
    granted_by: str | None = None  # "confirmation" | "approval_hook" | "session_grant" | None

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


class SafetyError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
