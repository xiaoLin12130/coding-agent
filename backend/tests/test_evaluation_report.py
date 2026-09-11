"""M9: the report and the threshold gate."""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.models import (
    AgentCaseResult,
    AgentReport,
    CategoryScore,
    DimensionScore,
    EvaluationThresholds,
    ParserCaseResult,
    ParserReport,
)
from app.evaluation.report import render_json, render_markdown, report_paths, write_report
from app.evaluation.runner import run_evaluation
from app.evaluation.thresholds import evaluate_thresholds


def parser_report(rate: float = 1.0, total: int = 50) -> ParserReport:
    passed = int(rate * total)
    return ParserReport(
        total=total,
        passed=passed,
        exact_match_rate=rate,
        by_category=[
            CategoryScore(category=name, total=1, passed=1, rate=1.0)
            for name in (
                "standard_json",
                "code_fence",
                "json5",
                "multiple_calls",
                "bracket_error",
                "missing_field",
                "invalid_json",
                "mixed_text",
            )
        ],
        results=[
            ParserCaseResult(id="case-" + str(i), category="standard_json", passed=i < passed)
            for i in range(total)
        ],
    )


DIMENSIONS = (
    "tool_selection",
    "tool_parsing",
    "task_completion",
    "recovery",
    "safety",
    "context_switching",
)


def agent_report(rate: float = 1.0) -> AgentReport:
    # Two cases per dimension, so the coverage threshold (10) is satisfied and a
    # failure in this helper can only mean the dimension checks themselves.
    results = [
        AgentCaseResult(id="agent-" + name + "-" + str(index), dimension=name, passed=True)
        for name in DIMENSIONS
        for index in range(2)
    ]
    return AgentReport(
        total=len(results),
        passed=len(results),
        pass_rate=rate,
        by_dimension=[
            DimensionScore(dimension=name, total=2, passed=2, rate=1.0) for name in DIMENSIONS
        ],
        results=results,
    )


def test_thresholds_pass_on_a_clean_run() -> None:
    gate = evaluate_thresholds(parser_report(), agent_report())
    assert gate.ok
    assert not gate.failures
    assert {check.name for check in gate.checks} >= {
        "parser.exact_match_rate",
        "parser.categories",
        "agent.pass_rate",
        "agent.dimensions",
    }


def test_a_parser_regression_fails_the_gate() -> None:
    gate = evaluate_thresholds(parser_report(rate=0.9), agent_report())
    assert not gate.ok
    assert [check.name for check in gate.failures] == ["parser.exact_match_rate"]


def test_a_missing_dimension_fails_the_gate() -> None:
    report = agent_report()
    report.by_dimension = [score for score in report.by_dimension if score.dimension != "safety"]
    gate = evaluate_thresholds(parser_report(), report)
    assert not gate.ok
    assert "agent.dimensions" in [check.name for check in gate.failures]


def test_too_few_cases_fails_the_coverage_check() -> None:
    gate = evaluate_thresholds(
        parser_report(total=3), agent_report(), EvaluationThresholds(min_parser_cases=40)
    )
    assert not gate.ok
    assert "parser.coverage" in [check.name for check in gate.failures]


def test_a_dimension_that_regresses_names_itself() -> None:
    report = agent_report()
    report.by_dimension[0] = DimensionScore(
        dimension="tool_selection", total=4, passed=3, rate=0.75
    )
    gate = evaluate_thresholds(parser_report(), report)
    assert not gate.ok
    assert [check.name for check in gate.failures] == ["agent.dimension.tool_selection"]


def test_markdown_shows_failures_and_limitations() -> None:
    report = run_evaluation()
    report.parser.results[0] = ParserCaseResult(
        id="broken-case",
        category="standard_json",
        passed=False,
        differences=["expected 1 call(s), got 0"],
        known_gap="a documented limitation",
    )
    markdown = render_markdown(report)
    assert "# Evaluation report (M9)" in markdown
    assert "broken-case" in markdown
    assert "expected 1 call(s), got 0" in markdown
    assert "Documented limitations" in markdown
    assert "| parser.exact_match_rate |" in markdown


def test_json_holds_the_whole_report() -> None:
    payload = json.loads(render_json(run_evaluation()))
    assert payload["ok"] is True
    assert payload["parser"]["total"] >= 40
    assert payload["agent"]["total"] >= 10
    assert payload["thresholds"]["ok"] is True
    assert len(payload["agent"]["by_dimension"]) == 6


def test_a_report_is_written_as_both_forms(tmp_path: Path) -> None:
    report = run_evaluation(suites=("parser",))
    paths = write_report(report, tmp_path / "run")
    assert paths["markdown"].exists()
    assert paths["json"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["parser"]["passed"] >= 40
    assert "Evaluation report" in paths["markdown"].read_text(encoding="utf-8")


def test_report_paths_are_inside_the_runs_directory() -> None:
    paths = report_paths(stamp="20260101-000000")
    assert paths["json"].name == "report.json"
    assert paths["directory"].name == "20260101-000000"
    assert "evaluation" in str(paths["directory"])


def test_a_single_suite_run_leaves_the_other_empty() -> None:
    report = run_evaluation(suites=("parser",))
    assert report.ok
    assert report.parser.total >= 40
    assert report.agent is None, "a suite that did not run is absent, not empty"
    assert report.suites == ["parser"]
