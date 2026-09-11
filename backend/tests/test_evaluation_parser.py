"""M9: the parser evaluation harness."""

from __future__ import annotations

from typing import Any

from app.evaluation.models import (
    CallExpectation,
    ParserCase,
    ParserExpectation,
)
from app.evaluation.parser_eval import evaluate_parser, run_parser_case
from app.tools.models import ParseOutcome, ParseIssue, ToolCall


def make_case(text: str, calls=None, issues=None, ok=True, fmt="json") -> ParserCase:
    return ParserCase(
        id="inline",
        category="standard_json",
        input=text,
        expect=ParserExpectation(
            ok=ok,
            format=fmt,
            calls=[CallExpectation(name=name, arguments=args) for name, args in (calls or [])],
            issue_codes=issues or [],
        ),
    )


class FakeParser:
    """A parser with a chosen behaviour, for testing the harness itself."""

    def __init__(self, outcome: ParseOutcome) -> None:
        self.outcome = outcome
        self.seen: list[tuple[str, Any]] = []

    def __call__(self, text: str, known_tools=None, max_calls: int = 16) -> ParseOutcome:
        self.seen.append((text, known_tools))
        return self.outcome


def test_the_golden_set_passes() -> None:
    report = evaluate_parser()
    assert report.total >= 40
    assert report.passed == report.total
    assert report.exact_match_rate == 1.0
    assert not report.failures


def test_the_report_scores_every_category() -> None:
    report = evaluate_parser()
    categories = {score.category for score in report.by_category}
    assert {"standard_json", "code_fence", "json5", "multiple_calls"} <= categories
    for score in report.by_category:
        assert score.rate == 1.0, score.category


def test_a_regression_is_detected_with_a_specific_difference() -> None:
    """If the parser stops finding a call, the harness must say exactly that."""
    silent = FakeParser(ParseOutcome(format="none", raw=""))
    case = make_case('{"name": "read_file", "arguments": {"path": "a.txt"}}',
                     calls=[("read_file", {"path": "a.txt"})])
    result = run_parser_case(case, known_tools={"read_file"})
    assert result.passed

    from app.evaluation import parser_eval

    original = parser_eval.parse_tool_calls
    parser_eval.parse_tool_calls = silent
    try:
        failed = run_parser_case(case, known_tools={"read_file"})
    finally:
        parser_eval.parse_tool_calls = original

    assert not failed.passed
    assert any("expected 1 call(s), got 0" in problem for problem in failed.differences)
    assert any("expected ok=True, got False" in problem for problem in failed.differences)


def test_a_wrong_tool_name_and_arguments_are_reported_separately() -> None:
    outcome = ParseOutcome(
        format="json",
        raw="x",
        calls=[
            ToolCall(id="call-1", name="write_file", arguments={"path": "b.txt"}, index=0)
        ],
    )
    from app.evaluation import parser_eval

    original = parser_eval.parse_tool_calls
    parser_eval.parse_tool_calls = FakeParser(outcome)
    try:
        result = run_parser_case(
            make_case("x", calls=[("read_file", {"path": "a.txt"})]), known_tools={"read_file"}
        )
    finally:
        parser_eval.parse_tool_calls = original

    assert not result.passed
    assert any("expected tool 'read_file', got 'write_file'" in d for d in result.differences)
    assert any("expected arguments {'path': 'a.txt'}" in d for d in result.differences)


def test_a_missing_or_extra_issue_is_reported() -> None:
    outcome = ParseOutcome(
        format="none", raw="x", issues=[ParseIssue(code="unknown_tool", message="nope")]
    )
    from app.evaluation import parser_eval

    original = parser_eval.parse_tool_calls
    parser_eval.parse_tool_calls = FakeParser(outcome)
    try:
        result = run_parser_case(make_case("x", ok=False, fmt="none", issues=["missing_name"]))
    finally:
        parser_eval.parse_tool_calls = original

    assert not result.passed
    assert any("expected issue codes ['missing_name'], got ['unknown_tool']" in d
               for d in result.differences)


def test_the_cases_are_parsed_with_the_real_tool_names() -> None:
    """A case can ask for the registry, so an invented tool is really caught."""
    outcome = ParseOutcome(format="json", raw="x")
    fake = FakeParser(outcome)
    from app.evaluation import parser_eval

    original = parser_eval.parse_tool_calls
    parser_eval.parse_tool_calls = fake
    try:
        run_parser_case(make_case("x", ok=False, fmt="json", issues=["unknown_tool"]))
        without = fake.seen[-1][1]
        case = make_case("x", ok=False, fmt="json", issues=["unknown_tool"]).model_copy(
            update={"known_tools": False}
        )
        run_parser_case(case)
        with_registry = fake.seen[-1][1]
    finally:
        parser_eval.parse_tool_calls = original

    assert "read_file" in without
    assert with_registry is None


def test_evaluation_is_offline_and_repeatable() -> None:
    first = evaluate_parser()
    second = evaluate_parser()
    assert first.passed == second.passed == first.total
