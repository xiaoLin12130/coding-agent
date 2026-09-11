"""Models for the recovery layer (M6).

Recovery is about continuing a task after something broke: a context that hit
its threshold, a browser page that died, a login that expired, a crashed
program, or a WebSocket client that reconnected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# What we are recovering from.
RecoveryKind = Literal[
    "context_soft",
    "context_hard",
    "browser_crash",
    "login_expired",
    "program_restart",
    "websocket_reconnect",
]

# How the attempt ended.
RecoveryOutcome = Literal["recovered", "not_needed", "failed"]

# ok    - nothing to do
# soft  - compact what we carry, keep the session
# hard  - archive the session and continue in a fresh seeded one
PressureLevel = Literal["ok", "soft", "hard"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContextThresholds(BaseModel):
    """Where the context starts to hurt.

    Ratios of the builder's budget, so the policy follows the budget wherever
    it is configured instead of duplicating a character count.
    """

    model_config = ConfigDict(extra="forbid")

    soft_ratio: float = Field(default=0.7, gt=0, le=1)
    hard_ratio: float = Field(default=0.9, gt=0, le=1)
    # When soft, carry this many recent turns instead of the builder's default.
    soft_recent_turns: int = Field(default=2, ge=0)
    min_recent_turns: int = Field(default=1, ge=0)

    def validate_order(self) -> None:
        if self.soft_ratio > self.hard_ratio:
            raise ValueError("soft_ratio must not exceed hard_ratio")


class ContextPressure(BaseModel):
    """How full the context is right now."""

    model_config = ConfigDict(extra="forbid")

    level: PressureLevel
    used_chars: int
    budget_chars: int
    ratio: float
    dropped_sections: list[str] = Field(default_factory=list)

    @property
    def needs_rotation(self) -> bool:
        return self.level == "hard"


class RecoveryStep(BaseModel):
    """One thing a recovery did, in order."""

    model_config = ConfigDict(extra="forbid")

    action: str
    ok: bool = True
    detail: str = ""


class RecoveryReport(BaseModel):
    """The result of one recovery attempt."""

    model_config = ConfigDict(extra="forbid")

    kind: RecoveryKind
    outcome: RecoveryOutcome
    steps: list[RecoveryStep] = Field(default_factory=list)
    message: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utc_now)

    @property
    def recovered(self) -> bool:
        return self.outcome == "recovered"

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"

    def notes(self) -> list[str]:
        return [step.action for step in self.steps]

    def render(self) -> str:
        lines = [self.kind + ": " + self.outcome + (" - " + self.message if self.message else "")]
        for step in self.steps:
            lines.append("  " + ("ok  " if step.ok else "FAIL") + " " + step.action
                         + (" - " + step.detail if step.detail else ""))
        return "\n".join(lines)


class RunRecoveryPlan(BaseModel):
    """What a restart found and would continue."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task: str
    step: int
    session_id: str
    status: str | None = None
    checkpoint_path: str
    resumable: bool = True
    reason: str = ""
    updated_at: datetime | None = None


class RecoverySnapshot(BaseModel):
    """Everything a reconnecting client needs to re-sync (WS disconnect)."""

    model_config = ConfigDict(extra="forbid")

    active_session_id: str | None = None
    session_message_count: int = 0
    archived_session_ids: list[str] = Field(default_factory=list)
    memory_count: int = 0
    latest_run: RunRecoveryPlan | None = None
    context_pressure: ContextPressure | None = None
    taken_at: datetime = Field(default_factory=utc_now)
