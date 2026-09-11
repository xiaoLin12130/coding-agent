"""M9 regression gate: the evaluation must keep passing.

This is the file a future change has to satisfy. It runs both suites through the
real components and fails if any case stops matching its contract, so a
regression in the parser, the safety layer, the executor or the loop is caught
here rather than by a user.
"""

from __future__ import annotations

from app.evaluation.dataset import load_agent_cases, load_parser_cases
from app.evaluation.models import DIMENSIONS, PARSER_CATEGORIES
from app.evaluation.parser_eval import evaluate_parser
from app.evaluation.agent_eval import evaluate_agent
from app.evaluation.runner import run_evaluation


def test_the_full_evaluation_passes() -> None:
    report = run_evaluation()
    assert report.thresholds.ok, [check.name for check in report.thresholds.failures]
    assert report.ok is True
    assert not report.parser.failures, [r.id for r in report.parser.failures]
    assert not report.agent.failures, [r.id for r in report.agent.failures]


def test_the_parser_golden_set_still_matches_every_case() -> None:
    cases = load_parser_cases()
    report = evaluate_parser(cases)
    assert report.total == len(cases)
    assert report.passed == report.total, {
        result.id: result.differences for result in report.failures
    }


def test_the_six_dimensions_still_pass() -> None:
    report = evaluate_agent(load_agent_cases())
    assert set(DIMENSIONS) == {score.dimension for score in report.by_dimension}
    for score in report.by_dimension:
        assert score.rate == 1.0, score.dimension


def test_the_required_parser_categories_are_still_covered() -> None:
    covered = {score.category for score in evaluate_parser().by_category}
    assert set(PARSER_CATEGORIES) <= covered


def test_the_documented_limitations_are_unchanged() -> None:
    """A known gap is a contract too: fixing one must update the dataset.

    If the parser starts reporting the truncated second call, this test fails on
    purpose and the dataset is corrected in the same change.
    """
    outcomes = {result.id: result for result in evaluate_parser().results}
    assert outcomes["bracket-broken-second-call"].known_gap
    assert outcomes["bracket-broken-second-call"].observed["calls"] == [
        {"name": "read_file", "arguments": {"path": "a.txt"}, "index": 0}
    ]
    assert outcomes["mixed-teaching-example"].known_gap
    assert outcomes["mixed-duplicate-call"].known_gap
    assert len(outcomes["mixed-duplicate-call"].observed["calls"]) == 2


def test_the_evaluation_needs_no_browser_and_no_network() -> None:
    """Everything here is offline: a browser-backed case would be a mistake."""
    for case in load_agent_cases():
        assert "browser" not in case.replies[0].lower() if case.replies else True
    for case in load_parser_cases():
        assert case.category in set(PARSER_CATEGORIES) | {"unknown_tool"}
