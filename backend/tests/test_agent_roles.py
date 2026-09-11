"""Role definitions and verdict parsing (M7)."""

from __future__ import annotations

import pytest

from app.agents.roles import (
    DEFAULT_ROLES,
    READ_ONLY_TOOLS,
    get_role,
    parse_review,
    parse_safety,
)
from app.agents.models import RoleSpec


def test_all_six_roles_exist() -> None:
    assert set(DEFAULT_ROLES) == {
        "planner",
        "coder",
        "reviewer",
        "memory_curator",
        "state_keeper",
        "safety_guard",
    }


def test_every_role_declares_a_purpose_and_a_prompt() -> None:
    for role in DEFAULT_ROLES.values():
        assert role.purpose
        assert role.system_prompt
        assert role.max_steps >= 1


def test_the_planner_cannot_write() -> None:
    """docs/runtime-agents.md: the Planner does not modify files."""
    planner = get_role("planner")

    assert planner.allowed_tools == READ_ONLY_TOOLS
    assert "write_file" not in planner.allowed_tools
    assert "apply_patch" not in planner.allowed_tools
    assert "run_shell" not in planner.allowed_tools


def test_the_memory_curator_can_only_propose() -> None:
    """It judges long-lived knowledge and proposes; it never writes memory."""
    curator = get_role("memory_curator")

    assert curator.allowed_tools == ["memory_propose"]


def test_the_state_keeper_updates_state_through_the_tool() -> None:
    keeper = get_role("state_keeper")

    assert "update_project_state" in keeper.allowed_tools
    assert "write_file" not in keeper.allowed_tools


def test_the_reviewer_can_verify_but_not_change() -> None:
    reviewer = get_role("reviewer")

    assert "read_file" in reviewer.allowed_tools
    assert "run_shell" in reviewer.allowed_tools, "it must be able to run the tests"
    assert "write_file" not in reviewer.allowed_tools
    assert "apply_patch" not in reviewer.allowed_tools


def test_the_coder_has_the_write_tools() -> None:
    coder = get_role("coder")

    assert {"write_file", "apply_patch", "run_shell"} <= set(coder.allowed_tools)


def test_the_safety_guard_cannot_change_anything() -> None:
    guard = get_role("safety_guard")

    assert set(guard.allowed_tools) <= set(READ_ONLY_TOOLS)


def test_roles_that_report_a_verdict_say_so() -> None:
    assert get_role("reviewer").verdict_kind == "review"
    assert get_role("safety_guard").verdict_kind == "safety"
    assert get_role("coder").verdict_kind == "none"


def test_an_unknown_role_is_rejected() -> None:
    with pytest.raises(KeyError):
        get_role("architect")


# --- review verdicts -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("VERDICT: APPROVED", "approved"),
        ("verdict: approved", "approved"),
        ("VERDICT:APPROVED", "approved"),
        ("VERDICT: NEEDS_FIX", "needs_fix"),
        ("VERDICT: needs-fix", "needs_fix"),
        ("VERDICT: FAILED", "needs_fix"),
        ("VERDICT: REJECT", "needs_fix"),
    ],
)
def test_review_verdicts_are_parsed(text: str, expected: str) -> None:
    verdict, _issues, _notes = parse_review(text)
    assert verdict == expected


def test_review_issues_and_notes_are_parsed() -> None:
    text = (
        "VERDICT: NEEDS_FIX\n"
        "ISSUE: add() still subtracts\n"
        "ISSUE: no test was run\n"
        "NOTES: the patch touched the right file"
    )

    verdict, issues, notes = parse_review(text)

    assert verdict == "needs_fix"
    assert issues == ["add() still subtracts", "no test was run"]
    assert notes == "the patch touched the right file"


def test_a_review_without_a_verdict_is_unknown() -> None:
    """Unparseable must not be read as approval."""
    verdict, issues, _notes = parse_review("I looked at the files and it seems okay.")

    assert verdict == "unknown"
    assert issues == []


def test_an_empty_review_is_unknown() -> None:
    assert parse_review("")[0] == "unknown"
    assert parse_review(None)[0] == "unknown"  # type: ignore[arg-type]


def test_a_verdict_inside_prose_is_still_found() -> None:
    text = "I checked everything.\nVERDICT: APPROVED\nNOTES: fine"

    assert parse_review(text)[0] == "approved"


# --- safety verdicts -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("VERDICT: SAFE", "safe"),
        ("VERDICT: BLOCKED", "blocked"),
        ("VERDICT: UNSAFE", "blocked"),
        ("VERDICT: DENY", "blocked"),
    ],
)
def test_safety_verdicts_are_parsed(text: str, expected: str) -> None:
    assert parse_safety(text)[0] == expected


def test_a_safety_answer_without_a_verdict_is_unknown_not_safe() -> None:
    assert parse_safety("looks fine to me")[0] == "unknown"


def test_safety_issues_are_parsed() -> None:
    verdict, issues, _notes = parse_safety(
        "VERDICT: BLOCKED\nISSUE: writes outside the project"
    )

    assert verdict == "blocked"
    assert issues == ["writes outside the project"]
