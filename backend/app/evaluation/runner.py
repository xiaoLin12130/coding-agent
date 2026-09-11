"""Running the evaluation suites (M9)."""

from __future__ import annotations

import time

from .agent_eval import evaluate_agent
from .models import EvaluationReport, EvaluationThresholds
from .parser_eval import evaluate_parser
from .thresholds import evaluate_thresholds

SUITES = ("parser", "agent")


def run_evaluation(
    suites: tuple[str, ...] | list[str] = SUITES,
    thresholds: EvaluationThresholds | None = None,
) -> EvaluationReport:
    """Run the requested suites and gate the result."""
    started = time.monotonic()
    parser = evaluate_parser() if "parser" in suites else None
    agent = evaluate_agent() if "agent" in suites else None
    gate = evaluate_thresholds(parser, agent, thresholds)
    return EvaluationReport(
        ok=gate.ok,
        parser=parser,
        agent=agent,
        thresholds=gate,
        suites=[name for name in SUITES if name in suites],
        duration_ms=int((time.monotonic() - started) * 1000),
    )
