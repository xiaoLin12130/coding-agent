"""Offline parser evaluation (M9).

Runs every golden case through the REAL ToolCallParser and reports the
difference between what the parser produced and what the case requires. The
harness never fixes the expectations to whatever the code happens to do: a case
that does not match fails, and a case with a documented limitation says so in
its own field.
"""

from __future__ import annotations

import time

from ..tools.parser import parse_tool_calls
from .dataset import known_tool_names, load_parser_cases
from .models import (
    CategoryScore,
    ParserCase,
    ParserCaseResult,
    ParserExpectation,
    ParserReport,
)


def _observed(outcome) -> dict:
    return {
        "ok": outcome.ok,
        "format": outcome.format,
        "calls": [
            {"name": call.name, "arguments": call.arguments, "index": call.index}
            for call in outcome.calls
        ],
        "issue_codes": [issue.code for issue in outcome.issues],
    }


def _call_problems(expected: ParserExpectation, outcome) -> list[str]:
    problems: list[str] = []
    if len(outcome.calls) != len(expected.calls):
        problems.append(
            "expected " + str(len(expected.calls)) + " call(s), got " + str(len(outcome.calls))
        )
    for position, wanted in enumerate(expected.calls):
        if position >= len(outcome.calls):
            problems.append(
                "call " + str(position) + " (" + wanted.name + ") is missing"
            )
            continue
        actual = outcome.calls[position]
        if actual.name != wanted.name:
            problems.append(
                "call "
                + str(position)
                + ": expected tool '"
                + wanted.name
                + "', got '"
                + actual.name
                + "'"
            )
        if dict(actual.arguments) != dict(wanted.arguments):
            problems.append(
                "call "
                + str(position)
                + ": expected arguments "
                + str(dict(wanted.arguments))
                + ", got "
                + str(dict(actual.arguments))
            )
        if actual.index != position:
            problems.append(
                "call " + str(position) + " has index " + str(actual.index)
            )
    return problems


def _issue_problems(expected: ParserExpectation, outcome) -> list[str]:
    wanted = sorted(expected.issue_codes)
    got = sorted(issue.code for issue in outcome.issues)
    if wanted == got:
        return []
    return ["expected issue codes " + str(wanted) + ", got " + str(got)]


def run_parser_case(case: ParserCase, known_tools: set[str] | None = None) -> ParserCaseResult:
    """Parse one case and compare the outcome with its contract."""
    started = time.monotonic()
    names = known_tools if known_tools is not None else known_tool_names()
    outcome = parse_tool_calls(case.input, known_tools=names if case.known_tools else None)
    expected = case.expect

    differences: list[str] = []
    if outcome.ok != expected.ok:
        differences.append("expected ok=" + str(expected.ok) + ", got " + str(outcome.ok))
    if outcome.format != expected.format:
        differences.append(
            "expected format '" + expected.format + "', got '" + outcome.format + "'"
        )
    differences.extend(_call_problems(expected, outcome))
    differences.extend(_issue_problems(expected, outcome))

    return ParserCaseResult(
        id=case.id,
        category=case.category,
        passed=not differences,
        differences=differences,
        observed=_observed(outcome),
        known_gap=case.known_gap,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def evaluate_parser(cases: list[ParserCase] | None = None) -> ParserReport:
    """Evaluate the golden set (or the cases handed in)."""
    started = time.monotonic()
    selected = cases if cases is not None else load_parser_cases()
    names = known_tool_names()
    results = [run_parser_case(case, names) for case in selected]

    categories: dict[str, list[ParserCaseResult]] = {}
    for result in results:
        categories.setdefault(result.category, []).append(result)
    scores = [
        CategoryScore(
            category=category,
            total=len(items),
            passed=sum(1 for item in items if item.passed),
            rate=sum(1 for item in items if item.passed) / len(items),
        )
        for category, items in sorted(categories.items())
    ]
    passed = sum(1 for result in results if result.passed)
    return ParserReport(
        total=len(results),
        passed=passed,
        exact_match_rate=(passed / len(results)) if results else 0.0,
        by_category=scores,
        results=results,
        duration_ms=int((time.monotonic() - started) * 1000),
    )

