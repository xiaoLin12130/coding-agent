"""Turning an evaluation run into a pass/fail gate (M9).

A report nobody acts on is decoration. These thresholds are what the regression
test asserts, so a change that breaks the parser or an agent dimension fails the
suite instead of quietly lowering a number in a report.
"""

from __future__ import annotations

from .models import (
    DIMENSIONS,
    PARSER_CATEGORIES,
    AgentReport,
    EvaluationThresholds,
    ParserReport,
    ThresholdCheck,
    ThresholdReport,
)


def evaluate_thresholds(
    parser: ParserReport | None = None,
    agent: AgentReport | None = None,
    thresholds: EvaluationThresholds | None = None,
) -> ThresholdReport:
    """Check the reports against the thresholds that must hold."""
    limits = thresholds or EvaluationThresholds()
    checks: list[ThresholdCheck] = []

    if parser is not None:
        checks.append(
            ThresholdCheck(
                name="parser.exact_match_rate",
                ok=parser.exact_match_rate >= limits.parser_exact_match_rate,
                detail=(
                    "exact match rate "
                    + _rate(parser.exact_match_rate)
                    + " (required "
                    + _rate(limits.parser_exact_match_rate)
                    + " over "
                    + str(parser.total)
                    + " case(s))"
                ),
            )
        )
        checks.append(
            ThresholdCheck(
                name="parser.coverage",
                ok=parser.total >= limits.min_parser_cases,
                detail=""
                + str(parser.total)
                + " case(s) (required at least "
                + str(limits.min_parser_cases)
                + ")",
            )
        )
        covered = {score.category for score in parser.by_category}
        absent = [name for name in PARSER_CATEGORIES if name not in covered]
        checks.append(
            ThresholdCheck(
                name="parser.categories",
                ok=not absent,
                detail=(
                    "all required categories are covered"
                    if not absent
                    else "missing category: " + ", ".join(absent)
                ),
            )
        )

    if agent is not None:
        checks.append(
            ThresholdCheck(
                name="agent.pass_rate",
                ok=agent.pass_rate >= limits.agent_pass_rate,
                detail=(
                    "pass rate "
                    + _rate(agent.pass_rate)
                    + " (required "
                    + _rate(limits.agent_pass_rate)
                    + " over "
                    + str(agent.total)
                    + " case(s))"
                ),
            )
        )
        checks.append(
            ThresholdCheck(
                name="agent.coverage",
                ok=agent.total >= limits.min_agent_cases,
                detail=""
                + str(agent.total)
                + " case(s) (required at least "
                + str(limits.min_agent_cases)
                + ")",
            )
        )
        covered = {score.dimension for score in agent.by_dimension}
        absent = [name for name in DIMENSIONS if name not in covered]
        checks.append(
            ThresholdCheck(
                name="agent.dimensions",
                ok=not absent,
                detail=(
                    "all six dimensions are covered"
                    if not absent
                    else "missing dimension: " + ", ".join(absent)
                ),
            )
        )
        for score in agent.by_dimension:
            checks.append(
                ThresholdCheck(
                    name="agent.dimension." + score.dimension,
                    ok=score.rate >= limits.dimension_pass_rate,
                    detail=_rate(score.rate)
                    + " of "
                    + str(score.total)
                    + " case(s)",
                )
            )

    return ThresholdReport(
        ok=all(check.ok for check in checks),
        thresholds=limits,
        checks=checks,
    )


def _rate(value: float) -> str:
    return format(value * 100, ".1f") + "%"
