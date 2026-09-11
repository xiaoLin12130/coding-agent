"""Evaluation (M9).

Two things live here:

* the offline harness that replays the golden parser set and the agent
  scenarios through the REAL components (parser, SafetyLayer, Executor,
  AgentLoop), and
* the thresholds that turn the result into a pass/fail gate, so a regression is
  caught by the test suite instead of by a user.

Nothing in this package is imported by the runtime: evaluation observes the
system, it is not part of it.
"""

from __future__ import annotations

from .agent_eval import evaluate_agent, run_agent_case
from .dataset import load_agent_cases, load_parser_cases
from .models import (
    AgentCase,
    AgentCaseResult,
    AgentReport,
    DimensionScore,
    EvaluationReport,
    EvaluationThresholds,
    ParserCase,
    ParserCaseResult,
    ParserReport,
    ThresholdReport,
)
from .parser_eval import evaluate_parser, run_parser_case
from .report import render_json, render_markdown, report_paths, write_report
from .runner import run_evaluation
from .thresholds import evaluate_thresholds

__all__ = [
    "AgentCase",
    "AgentCaseResult",
    "AgentReport",
    "DimensionScore",
    "EvaluationReport",
    "EvaluationThresholds",
    "ParserCase",
    "ParserCaseResult",
    "ParserReport",
    "ThresholdReport",
    "evaluate_agent",
    "evaluate_parser",
    "evaluate_thresholds",
    "load_agent_cases",
    "load_parser_cases",
    "render_json",
    "render_markdown",
    "report_paths",
    "run_agent_case",
    "run_evaluation",
    "run_parser_case",
    "write_report",
]
