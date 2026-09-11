"""Rendering an evaluation report (M9).

Two forms of the same result: machine-readable JSON for a gate, markdown for a
human. Both show the failures with the difference that produced them, because a
report that only shows a percentage cannot be acted on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import runs_dir
from .models import AgentReport, EvaluationReport, ParserReport


def report_paths(directory: Path | str | None = None, stamp: str | None = None) -> dict[str, Path]:
    """Where a report is written: runs/evaluation/<stamp>/."""
    name = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = Path(directory) if directory is not None else runs_dir() / "evaluation" / name
    return {"directory": base, "json": base / "report.json", "markdown": base / "report.md"}


def render_json(report: EvaluationReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def write_report(report: EvaluationReport, directory: Path | str | None = None) -> dict[str, Path]:
    """Write both forms and return their paths."""
    paths = report_paths(directory)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(render_json(report), encoding="utf-8")
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    return paths


def render_markdown(report: EvaluationReport) -> str:
    lines: list[str] = []
    lines.append("# Evaluation report (M9)")
    lines.append("")
    lines.append("- generated: " + report.generated_at.isoformat())
    lines.append("- suites: " + (", ".join(report.suites) or "(none)"))
    lines.append("- duration: " + str(report.duration_ms) + " ms")
    lines.append("- result: " + ("PASS" if report.ok else "FAIL"))
    lines.append("")

    if report.parser is not None:
        lines.extend(_parser_section(report.parser))
    if report.agent is not None:
        lines.extend(_agent_section(report.agent))

    lines.append("## Thresholds")
    lines.append("")
    lines.append("| check | result | detail |")
    lines.append("|---|---|---|")
    for check in report.thresholds.checks:
        lines.append(
            "| " + check.name + " | " + ("pass" if check.ok else "FAIL") + " | " + check.detail + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _parser_section(parser: ParserReport) -> list[str]:
    lines = ["## Parser golden set", ""]
    lines.append(
        "cases: "
        + str(parser.total)
        + " | passed: "
        + str(parser.passed)
        + " | exact match: "
        + format(parser.exact_match_rate * 100, ".1f")
        + "%"
    )
    lines.append("")
    lines.append("| category | cases | passed | rate |")
    lines.append("|---|---|---|---|")
    for score in parser.by_category:
        lines.append(
            "| "
            + score.category
            + " | "
            + str(score.total)
            + " | "
            + str(score.passed)
            + " | "
            + format(score.rate * 100, ".1f")
            + "% |"
        )
    lines.append("")
    failures = parser.failures
    if failures:
        lines.append("### Failures")
        lines.append("")
        for result in failures:
            lines.append("- **" + result.id + "** (" + result.category + ")")
            for difference in result.differences:
                lines.append("  - " + difference)
        lines.append("")
    gaps = parser.known_gaps
    if gaps:
        lines.append("### Documented limitations")
        lines.append("")
        for result in gaps:
            lines.append("- **" + result.id + "**: " + result.known_gap)
        lines.append("")
    return lines


def _agent_section(agent: AgentReport) -> list[str]:
    lines = ["## Agent evaluation", ""]
    lines.append(
        "cases: "
        + str(agent.total)
        + " | passed: "
        + str(agent.passed)
        + " | pass rate: "
        + format(agent.pass_rate * 100, ".1f")
        + "%"
    )
    lines.append("")
    lines.append("| dimension | cases | passed | rate |")
    lines.append("|---|---|---|---|")
    for score in agent.by_dimension:
        lines.append(
            "| "
            + score.dimension
            + " | "
            + str(score.total)
            + " | "
            + str(score.passed)
            + " | "
            + format(score.rate * 100, ".1f")
            + "% |"
        )
    lines.append("")
    for result in agent.results:
        marker = "pass" if result.passed else "FAIL"
        lines.append("### " + result.id + " (" + result.dimension + ") - " + marker)
        lines.append("")
        if result.explanation:
            lines.append(result.explanation)
            lines.append("")
        if result.error:
            lines.append("error: " + result.error)
            lines.append("")
        for check in result.checks:
            lines.append(
                "- "
                + ("ok" if check.ok else "FAILED")
                + " "
                + check.name
                + (": " + check.detail if check.detail else "")
            )
        if result.known_gap:
            lines.append("- documented limitation: " + result.known_gap)
        lines.append("")
    return lines
