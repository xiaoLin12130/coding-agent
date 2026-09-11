"""M9: the golden sets are data, and they are checked as data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.dataset import (
    DatasetError,
    agent_dataset_path,
    evaluation_dir,
    load_agent_cases,
    load_parser_cases,
    parser_dataset_path,
)
from app.evaluation.models import DIMENSIONS, PARSER_CATEGORIES


def test_the_golden_parser_set_loads() -> None:
    cases = load_parser_cases()
    assert len(cases) >= 40
    assert all(case.id and case.category and case.input for case in cases)
    assert len({case.id for case in cases}) == len(cases)


def test_every_required_parser_category_is_covered() -> None:
    covered = {case.category for case in load_parser_cases()}
    missing = [name for name in PARSER_CATEGORIES if name not in covered]
    assert not missing, "docs/testing.md requires these categories: " + ", ".join(missing)


def test_every_dimension_is_covered_by_a_scenario() -> None:
    covered = {case.dimension for case in load_agent_cases()}
    assert set(DIMENSIONS) <= covered


def test_a_parser_case_carries_a_contract_not_just_an_input() -> None:
    for case in load_parser_cases():
        assert case.expect.format, case.id
        if case.expect.ok:
            assert case.expect.calls, case.id
        else:
            assert case.expect.issue_codes, case.id


def test_a_scenario_states_what_it_measures() -> None:
    for case in load_agent_cases():
        assert case.task, case.id
        assert case.explanation, case.id
        # every case must assert something
        assert case.expect.model_dump(exclude_defaults=True), case.id


def test_the_documented_limitations_are_recorded_in_the_dataset() -> None:
    gaps = [case for case in load_parser_cases() if case.known_gap]
    assert {case.id for case in gaps} == {
        "bracket-broken-second-call",
        "mixed-teaching-example",
        "mixed-duplicate-call",
    }
    for case in gaps:
        assert len(case.known_gap) > 30, case.id


def test_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    line = json.dumps(
        {
            "id": "same",
            "category": "standard_json",
            "input": "{}",
            "expect": {"ok": False, "format": "none", "issue_codes": ["missing_name"]},
        }
    )
    path = tmp_path / "golden.jsonl"
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(DatasetError) as caught:
        load_parser_cases(path)
    assert "duplicate case id" in str(caught.value)


def test_a_malformed_line_names_its_line_number(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text('{"id": "a", "category": "x"}\n', encoding="utf-8")
    with pytest.raises(DatasetError) as caught:
        load_parser_cases(path)
    assert "line 1" in str(caught.value)


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DatasetError):
        load_parser_cases(tmp_path / "nope.jsonl")
    with pytest.raises(DatasetError):
        load_agent_cases(tmp_path / "nope.json")


def test_an_agent_file_that_is_not_a_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text('{"cases": []}', encoding="utf-8")
    with pytest.raises(DatasetError):
        load_agent_cases(path)


def test_the_dataset_directory_can_be_relocated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODING_AGENT_EVALUATION_DIR", str(tmp_path))
    assert evaluation_dir() == tmp_path
    assert parser_dataset_path() == tmp_path / "parser_golden.jsonl"
    assert agent_dataset_path() == tmp_path / "agent_cases.json"
