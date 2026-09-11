"""Loading the golden sets (M9).

The data lives in backend/evaluation/ as plain files that a human can read and
edit: a JSONL file of parser cases and a JSON file of agent scenarios. Nothing
about a case is hidden in code, and a new case needs no new code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import AgentCase, ParserCase

EVALUATION_DIR_ENV = "CODING_AGENT_EVALUATION_DIR"
PARSER_FILE = "parser_golden.jsonl"
AGENT_FILE = "agent_cases.json"


class DatasetError(RuntimeError):
    """A golden file is missing, malformed or ambiguous."""

    code = "dataset_error"


def evaluation_dir() -> Path:
    """Directory holding the golden sets (overridable for a deployment)."""
    override = os.environ.get(EVALUATION_DIR_ENV)
    if override:
        return Path(override).resolve()
    # backend/app/evaluation/dataset.py -> backend/app -> backend
    return Path(__file__).resolve().parents[2] / "evaluation"


def parser_dataset_path() -> Path:
    return evaluation_dir() / PARSER_FILE


def agent_dataset_path() -> Path:
    return evaluation_dir() / AGENT_FILE


def _read_lines(path: Path) -> list[tuple[int, str]]:
    if not path.exists():
        raise DatasetError("no such dataset file: " + str(path))
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            lines.append((number, line))
    if not lines:
        raise DatasetError("the dataset file is empty: " + str(path))
    return lines


def _check_unique(cases: list, path: Path) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise DatasetError("duplicate case id '" + case.id + "' in " + str(path))
        seen.add(case.id)


def load_parser_cases(path: Path | str | None = None) -> list[ParserCase]:
    """Read the golden parser set (one JSON object per line)."""
    file = Path(path) if path is not None else parser_dataset_path()
    cases: list[ParserCase] = []
    for number, line in _read_lines(file):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(
                "line " + str(number) + " of " + str(file) + " is not valid JSON: " + exc.msg
            ) from exc
        try:
            cases.append(ParserCase.model_validate(payload))
        except Exception as exc:  # noqa: BLE001 - re-raised with the line number
            raise DatasetError(
                "line " + str(number) + " of " + str(file) + " is not a valid case: " + str(exc)
            ) from exc
    _check_unique(cases, file)
    return cases


def load_agent_cases(path: Path | str | None = None) -> list[AgentCase]:
    """Read the agent scenario file (a JSON list of cases)."""
    file = Path(path) if path is not None else agent_dataset_path()
    if not file.exists():
        raise DatasetError("no such dataset file: " + str(file))
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(str(file) + " is not valid JSON: " + exc.msg) from exc
    if not isinstance(raw, list):
        raise DatasetError(str(file) + " must hold a list of cases")
    cases: list[AgentCase] = []
    for index, payload in enumerate(raw):
        try:
            cases.append(AgentCase.model_validate(payload))
        except Exception as exc:  # noqa: BLE001 - re-raised with the position
            raise DatasetError(
                "case " + str(index) + " of " + str(file) + " is not a valid case: " + str(exc)
            ) from exc
    _check_unique(cases, file)
    return cases


def known_tool_names() -> set[str]:
    """The tool names the shipped registry really has."""
    from ..tools.builtin import default_registry

    return set(default_registry().names())
