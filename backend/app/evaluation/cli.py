"""Evaluation command line (M9).

    cd backend
    python -m app.evaluation.cli run                 # both suites, writes a report
    python -m app.evaluation.cli run --suite parser --json
    python -m app.evaluation.cli run --out reports/m9

Exit code 0 means every threshold held; 1 means the evaluation found a
regression, which is what a CI job (or the regression test) reacts to.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .models import EvaluationThresholds
from .report import render_json, render_markdown, write_report
from .runner import run_evaluation


def _cmd_run(args: argparse.Namespace) -> int:
    suites = ("parser", "agent") if args.suite == "all" else (args.suite,)
    thresholds = EvaluationThresholds(
        parser_exact_match_rate=args.parser_rate,
        agent_pass_rate=args.agent_rate,
        dimension_pass_rate=args.dimension_rate,
    )
    report = run_evaluation(suites, thresholds)

    if args.out == "-":
        if args.json:
            print(render_json(report), end="")
        else:
            print(render_markdown(report), end="")
    else:
        paths = write_report(report, Path(args.out) if args.out else None)
        if args.json:
            print(render_json(report), end="")
        else:
            print(_summary(report))
            print()
            print("report: " + str(paths["markdown"]))
            print("json  : " + str(paths["json"]))
    return 0 if report.ok else 1


def _summary(report) -> str:
    lines = ["evaluation: " + ("PASS" if report.ok else "FAIL")]
    if report.parser is not None:
        lines.append(
            "  parser: "
            + str(report.parser.passed)
            + "/"
            + str(report.parser.total)
            + " case(s), exact match "
            + format(report.parser.exact_match_rate * 100, ".1f")
            + "%"
        )
        for result in report.parser.failures:
            lines.append("    FAIL " + result.id + ": " + "; ".join(result.differences))
    if report.agent is not None:
        lines.append(
            "  agent : "
            + str(report.agent.passed)
            + "/"
            + str(report.agent.total)
            + " case(s), pass rate "
            + format(report.agent.pass_rate * 100, ".1f")
            + "%"
        )
        for score in report.agent.by_dimension:
            lines.append(
                "    "
                + score.dimension.ljust(18)
                + str(score.passed)
                + "/"
                + str(score.total)
                + " ("
                + format(score.rate * 100, ".1f")
                + "%)"
            )
        for result in report.agent.failures:
            lines.append("    FAIL " + result.id + ": " + _failure_text(result))
    for check in report.thresholds.failures:
        lines.append("  THRESHOLD " + check.name + ": " + check.detail)
    return "\n".join(lines)


def _failure_text(result) -> str:
    if result.error:
        return result.error
    return "; ".join(
        check.name + " (" + check.detail + ")" for check in result.failures
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.evaluation.cli",
        description="Run the offline parser and agent evaluations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("run", help="run the suites and write a report")
    listing.add_argument("--suite", choices=("all", "parser", "agent"), default="all")
    listing.add_argument("--out", default="", help="report directory ('-' prints to stdout)")
    listing.add_argument("--json", action="store_true", help="print the report as JSON")
    listing.add_argument("--parser-rate", type=float, default=1.0)
    listing.add_argument("--agent-rate", type=float, default=1.0)
    listing.add_argument("--dimension-rate", type=float, default=1.0)
    listing.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
