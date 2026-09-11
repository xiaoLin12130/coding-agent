"""Models for the evaluation harness (M9).

A case file holds the INPUT and the CONTRACT (what the system must do with it).
The harness records what actually happened, so a report always shows the
difference rather than a summary that hides it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The six dimensions milestones/M9.md requires the agent to be evaluated on.
AgentDimension = Literal[
    "tool_selection",
    "tool_parsing",
    "task_completion",
    "recovery",
    "safety",
    "context_switching",
]

DIMENSIONS: tuple[str, ...] = (
    "tool_selection",
    "tool_parsing",
    "task_completion",
    "recovery",
    "safety",
    "context_switching",
)

# The eight categories docs/testing.md requires the golden parser set to cover.
PARSER_CATEGORIES: tuple[str, ...] = (
    "standard_json",
    "code_fence",
    "json5",
    "multiple_calls",
    "bracket_error",
    "missing_field",
    "invalid_json",
    "mixed_text",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# parser golden set
# ---------------------------------------------------------------------------


class CallExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ParserExpectation(BaseModel):
    """What the parser must produce for one input."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    format: str
    calls: list[CallExpectation] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)


class ParserCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    input: str
    # Parse with the real tool names, so an invented tool is reported.
    known_tools: bool = True
    expect: ParserExpectation
    note: str = ""
    # A documented limitation: the expectation still describes today's
    # behaviour, and the report lists the case so the gap stays visible.
    known_gap: str = ""


class ParserCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    passed: bool
    differences: list[str] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    known_gap: str = ""
    duration_ms: int = 0


class CategoryScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    total: int
    passed: int
    rate: float


class ParserReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    passed: int = 0
    exact_match_rate: float = 0.0
    by_category: list[CategoryScore] = Field(default_factory=list)
    results: list[ParserCaseResult] = Field(default_factory=list)
    duration_ms: int = 0

    @property
    def failures(self) -> list[ParserCaseResult]:
        return [result for result in self.results if not result.passed]

    @property
    def known_gaps(self) -> list[ParserCaseResult]:
        return [result for result in self.results if result.known_gap]


# ---------------------------------------------------------------------------
# agent scenarios
# ---------------------------------------------------------------------------


class AgentExpectation(BaseModel):
    """What one agent scenario must show.

    Every field is optional: a case states only what it is about, so the report
    does not imply coverage the case never claimed.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = ""
    tools_used: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)
    min_tool_calls: int | None = None
    max_tool_failures: int | None = None
    min_tool_failures: int | None = None
    files: dict[str, str] = Field(default_factory=dict)
    files_absent: list[str] = Field(default_factory=list)
    final_message_contains: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    transcript_roles: list[str] = Field(default_factory=list)
    parse_failures: int | None = None
    context_rotated: bool | None = None
    resume_completed: bool | None = None
    # Fragments that must appear in some tool result (evidence the work ran).
    tool_results_contain: list[str] = Field(default_factory=list)
    # Fragments that must appear NOWHERE in the run (a leak, or a command that
    # was supposed to be refused).
    never_in_output: list[str] = Field(default_factory=list)


class AgentCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension: str
    task: str
    # Files written into the case's throwaway workspace before the run.
    workspace: dict[str, str] = Field(default_factory=dict)
    # Files written NEXT TO the workspace, for the path-escape cases: the
    # safety layer must refuse a path outside the project root.
    outside_files: dict[str, str] = Field(default_factory=dict)
    # The model's replies, in order (the scripted provider's plan).
    replies: list[str] = Field(default_factory=list)
    final_message: str = "Done."
    # once | reject | none  - what the confirmation hook answers.
    confirm: str = "once"
    max_steps: int = 8
    max_tool_retries: int = 2
    max_parse_retries: int = 1
    # Context thresholds for the rotation cases (M6).
    soft_ratio: float | None = None
    hard_ratio: float | None = None
    # Recovery: fail this many model calls before answering.
    fail_first_calls: int = 0
    recover_model: bool = False
    # Recovery: stop after N steps, then resume from the checkpoint.
    resume_after_steps: int | None = None
    expect: AgentExpectation = Field(default_factory=AgentExpectation)
    explanation: str = ""
    known_gap: str = ""


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str = ""


class AgentCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension: str
    passed: bool
    checks: list[CheckResult] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    known_gap: str = ""
    duration_ms: int = 0
    explanation: str = ""

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.ok]


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    total: int
    passed: int
    rate: float


class AgentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    by_dimension: list[DimensionScore] = Field(default_factory=list)
    results: list[AgentCaseResult] = Field(default_factory=list)
    duration_ms: int = 0

    @property
    def failures(self) -> list[AgentCaseResult]:
        return [result for result in self.results if not result.passed]

    @property
    def known_gaps(self) -> list[AgentCaseResult]:
        return [result for result in self.results if result.known_gap]


# ---------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------


class EvaluationThresholds(BaseModel):
    """What a run must reach to count as a pass."""

    model_config = ConfigDict(extra="forbid")

    parser_exact_match_rate: float = 1.0
    agent_pass_rate: float = 1.0
    dimension_pass_rate: float = 1.0
    min_parser_cases: int = 40
    min_agent_cases: int = 10


class ThresholdCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str


class ThresholdReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)
    checks: list[ThresholdCheck] = Field(default_factory=list)

    @property
    def failures(self) -> list[ThresholdCheck]:
        return [check for check in self.checks if not check.ok]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    # A suite that did not run is absent, not an empty report: an empty report
    # would read as "ran and found nothing".
    parser: ParserReport | None = None
    agent: AgentReport | None = None
    thresholds: ThresholdReport = Field(default_factory=ThresholdReport)
    generated_at: datetime = Field(default_factory=utc_now)
    duration_ms: int = 0
    suites: list[str] = Field(default_factory=list)
