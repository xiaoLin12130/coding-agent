"""M9: the agent evaluation harness."""

from __future__ import annotations

from pathlib import Path

from app.evaluation.agent_eval import evaluate_agent, run_agent_case
from app.evaluation.models import AgentCase, AgentExpectation


def base_case(**kwargs) -> AgentCase:
    payload = {
        "id": "inline",
        "dimension": "task_completion",
        "task": "list the project directory",
        "workspace": {"a.txt": "hello\n"},
        "replies": [
            '{"name": "list_dir", "arguments": {"path": "."}}',
            "Listed it.",
        ],
        "expect": {"status": "completed", "tools_used": ["list_dir"]},
        "explanation": "an inline case for the harness itself",
    }
    payload.update(kwargs)
    return AgentCase.model_validate(payload)


def test_the_scenario_set_passes() -> None:
    report = evaluate_agent()
    assert report.total >= 10
    assert report.pass_rate == 1.0
    assert not report.failures
    assert {score.dimension for score in report.by_dimension} == {
        "tool_selection",
        "tool_parsing",
        "task_completion",
        "recovery",
        "safety",
        "context_switching",
    }


def test_every_dimension_scores_fully() -> None:
    report = evaluate_agent()
    for score in report.by_dimension:
        assert score.rate == 1.0, score.dimension


def test_a_scenario_runs_in_a_throwaway_workspace(tmp_path: Path) -> None:
    result = run_agent_case(base_case(), workdir=tmp_path)
    assert result.passed, result.checks
    # the workspace the case declares is created, and the run is isolated
    assert (tmp_path / "project" / "a.txt").read_text(encoding="utf-8") == "hello\n"
    assert (tmp_path / "project" / "state" / "sessions").exists()


def test_a_wrong_expectation_fails_with_a_readable_check() -> None:
    case = base_case(expect={"status": "timeout"})
    result = run_agent_case(case)
    assert not result.passed
    failed = [check for check in result.checks if not check.ok]
    assert [check.name for check in failed] == ["status"]
    assert "expected 'timeout', got 'completed'" in failed[0].detail


def test_a_file_expectation_compares_the_content_not_just_existence() -> None:
    case = base_case(
        replies=[
            '{"name": "write_file", "arguments": {"path": "out.txt", "content": "written"}}',
            "Done.",
        ],
        expect={"status": "completed", "files": {"out.txt": "written"}},
    )
    assert run_agent_case(case).passed

    wrong = base_case(
        replies=[
            '{"name": "write_file", "arguments": {"path": "out.txt", "content": "written"}}',
            "Done.",
        ],
        expect={"status": "completed", "files": {"out.txt": "something else"}},
    )
    result = run_agent_case(wrong)
    assert not result.passed
    assert [check.name for check in result.failures] == ["file:out.txt"]


def test_a_forbidden_tool_is_reported() -> None:
    case = base_case(expect={"status": "completed", "tools_forbidden": ["list_dir"]})
    result = run_agent_case(case)
    assert not result.passed
    assert "tool_not_used:list_dir" in [check.name for check in result.failures]


def test_a_broken_case_is_recorded_as_an_error_not_a_crash() -> None:
    case = base_case(soft_ratio=0.9, hard_ratio=0.1)
    result = run_agent_case(case)
    assert not result.passed
    assert "ValueError" in result.error
    assert result.observed == {}


def test_the_fault_injection_really_fails_the_first_call() -> None:
    """The recovery case is only meaningful if the model really broke first."""
    case = base_case(
        replies=[
            '{"name": "list_dir", "arguments": {"path": "."}}',
            "Listed it.",
        ],
        fail_first_calls=1,
        recover_model=True,
        expect={"status": "completed", "event_types": ["model_recovered"]},
    )
    assert run_agent_case(case).passed

    without_hook = base_case(
        replies=['{"name": "list_dir", "arguments": {"path": "."}}', "Listed it."],
        fail_first_calls=1,
        recover_model=False,
        expect={"status": "completed"},
    )
    result = run_agent_case(without_hook)
    assert not result.passed
    assert result.observed["status"] == "error"
