"""Models for the Context / State layer (M2).

Single source of truth for transcripts, context assembly, memory proposals
and session bookkeeping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["system", "user", "assistant", "tool"]

# Context section names in priority order (docs/state-context.md):
# system rules > current task > project state > memory > recent transcript
# > tool results > summary of older history.
SECTION_ORDER: tuple[str, ...] = (
    "system",
    "task",
    "project_state",
    "memory",
    "transcript",
    "tool_result",
    "history_summary",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


class TranscriptEntry(BaseModel):
    """One immutable message in a session transcript.

    'index' is the original message index inside its session: it survives
    summarisation so an agent can ask for the original again.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime
    tool_name: str | None = None
    tool_call_id: str | None = None
    meta: dict = Field(default_factory=dict)

    def one_line(self, limit: int = 160) -> str:
        text = " ".join(self.content.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"


class TranscriptSummary(BaseModel):
    """Extractive summary of the turns that no longer fit the context."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    text: str
    summarized_indices: list[int] = Field(default_factory=list)
    kept_indices: list[int] = Field(default_factory=list)
    summarized_count: int = 0
    kept_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


class ContextBudget(BaseModel):
    """Character budget for one assembled context.

    Characters are the budget unit because M2 has no tokenizer behind the
    provider boundary; the numbers stay configurable so a real token budget
    can replace them without touching the builder's logic.
    """

    model_config = ConfigDict(extra="forbid")

    max_chars: int = Field(default=28_000, gt=0)
    min_section_chars: int = Field(default=200, gt=0)
    head_ratio: float = Field(default=0.7, gt=0, le=1)
    never_drop: tuple[str, ...] = ("system", "task")


class ContextSection(BaseModel):
    """One included block of the assembled context."""

    model_config = ConfigDict(extra="forbid")

    name: str
    priority: int
    content: str
    original_chars: int
    included_chars: int
    truncated: bool = False
    omitted_chars: int = 0
    reference: str | None = None
    note: str = ""


class BuiltContext(BaseModel):
    """The exact information for one model turn."""

    model_config = ConfigDict(extra="forbid")

    sections: list[ContextSection] = Field(default_factory=list)
    dropped_sections: list[str] = Field(default_factory=list)
    budget_chars: int = 0
    total_chars: int = 0
    truncated: bool = False
    built_at: datetime = Field(default_factory=utc_now)

    def section(self, name: str) -> ContextSection | None:
        for entry in self.sections:
            if entry.name == name:
                return entry
        return None

    def render(self) -> str:
        parts: list[str] = []
        for entry in self.sections:
            parts.append(f"## {entry.name}\n{entry.content}")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Memory proposals
# ---------------------------------------------------------------------------

MemoryDecisionKind = Literal[
    "accepted",
    "updated",
    "duplicate",
    "conflict",
    "rejected_invalid",
    "rejected_sensitive",
]


class MemoryProposal(BaseModel):
    """What the model is allowed to emit. It is a proposal, not a write."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str
    namespace: str = "user"
    reason: str = ""
    source_turn: str | None = None
    proposed_by: str = "model"


class MemoryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: MemoryProposal
    decision: MemoryDecisionKind
    reason: str = ""
    stored_key: str | None = None


class MemoryReviewResult(BaseModel):
    """Outcome of the system-side review pipeline."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[MemoryDecision] = Field(default_factory=list)

    @property
    def accepted(self) -> list[MemoryDecision]:
        return [
            d for d in self.decisions if d.decision in ("accepted", "updated")
        ]

    @property
    def rejected(self) -> list[MemoryDecision]:
        return [d for d in self.decisions if d.decision not in ("accepted", "updated")]

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for decision in self.decisions:
            result[decision.decision] = result.get(decision.decision, 0) + 1
        return result


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived: bool = False
    message_count: int = 0
    turn_count: int = 0
    summary_path: str | None = None
    archive_path: str | None = None
    rotated_from: str | None = None


class SessionIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_session_id: str | None = None
    sessions: list[SessionInfo] = Field(default_factory=list)

    def find(self, session_id: str) -> SessionInfo | None:
        for info in self.sessions:
            if info.id == session_id:
                return info
        return None


class SessionSnapshot(BaseModel):
    """Everything needed to continue after a restart."""

    model_config = ConfigDict(extra="forbid")

    active_session_id: str
    created: bool = False
    recovered: bool = False
    entries: list[TranscriptEntry] = Field(default_factory=list)
    message_count: int = 0
    turn_count: int = 0
    archived_session_ids: list[str] = Field(default_factory=list)
    restored_at: datetime = Field(default_factory=utc_now)


class SessionRotation(BaseModel):
    """Result of rotating a session whose context approached the hard limit."""

    model_config = ConfigDict(extra="forbid")

    archived_session_id: str
    new_session_id: str
    reason: str
    summary: TranscriptSummary
    carried_entry_indices: list[int] = Field(default_factory=list)
    seed_entry_index: int | None = None
