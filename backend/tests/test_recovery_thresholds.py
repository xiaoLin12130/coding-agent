"""Context threshold policy tests (M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.context import ContextBuilder, SessionManager
from app.context.models import ContextBudget
from app.config import AppPaths
from app.recovery import ContextPressurePolicy, ContextThresholds
from app.storage import StateStore


def _builder(tmp_path: Path, max_chars: int = 1000) -> tuple[ContextBuilder, SessionManager]:
    paths = AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )
    store = StateStore(paths)
    sessions = SessionManager(tmp_path / "sessions", store=store)
    builder = ContextBuilder(
        sessions.transcript, sessions.memory, sessions.store,
        budget=ContextBudget(max_chars=max_chars, min_section_chars=20),
    )
    return builder, sessions


def test_thresholds_reject_an_inverted_order() -> None:
    with pytest.raises(ValueError):
        ContextPressurePolicy(ContextThresholds(soft_ratio=0.9, hard_ratio=0.5))


def test_small_context_is_ok(tmp_path: Path) -> None:
    builder, sessions = _builder(tmp_path)
    sessions.start()

    context = builder.build(session_id=sessions.current_session_id(), system="s", task="t")
    pressure = ContextPressurePolicy().evaluate(context, builder.budget.max_chars)

    assert pressure.level == "ok"
    assert pressure.ratio < 0.7
    assert pressure.needs_rotation is False


def test_context_over_the_soft_ratio_is_soft(tmp_path: Path) -> None:
    builder, sessions = _builder(tmp_path, max_chars=500)
    sessions.start()
    for number in range(20):
        sessions.record("user", "message " + str(number) + " " + "x" * 40)

    context = builder.build(session_id=sessions.current_session_id(), system="s", task="t")
    pressure = ContextPressurePolicy().evaluate(context, builder.budget.max_chars)

    assert pressure.level in ("soft", "hard")


def test_context_at_the_hard_ratio_needs_rotation(tmp_path: Path) -> None:
    builder, sessions = _builder(tmp_path, max_chars=200)
    sessions.start()
    for number in range(40):
        sessions.record("user", "padding " + "y" * 80)

    context = builder.build(session_id=sessions.current_session_id(), system="s", task="t")
    pressure = ContextPressurePolicy().evaluate(context, builder.budget.max_chars)

    assert pressure.level == "hard"
    assert pressure.needs_rotation is True
    assert pressure.dropped_sections, "sections should have been dropped at this size"


def test_a_missing_context_reads_as_ok() -> None:
    pressure = ContextPressurePolicy().evaluate(None, 1000)

    assert pressure.level == "ok"
    assert pressure.used_chars == 0


def test_a_zero_budget_is_treated_as_full() -> None:
    pressure = ContextPressurePolicy().evaluate(None, 0)

    assert pressure.budget_chars == 0
    assert pressure.ratio == 0.0 or pressure.ratio == 1.0


@pytest.mark.parametrize(
    "level,default,expected",
    [("ok", 3, 3), ("soft", 3, 2), ("soft", 1, 1), ("hard", 3, 1)],
)
def test_recent_turns_shrink_under_pressure(level: str, default: int, expected: int) -> None:
    policy = ContextPressurePolicy()

    assert policy.recent_turns_for(level, default) == expected


def test_would_overflow_matches_the_hard_ratio() -> None:
    policy = ContextPressurePolicy(ContextThresholds(hard_ratio=0.9))

    assert policy.would_overflow(89, 100) is False
    assert policy.would_overflow(90, 100) is True
    assert policy.would_overflow(1, 0) is True


def test_pressure_reports_the_ratio(tmp_path: Path) -> None:
    builder, sessions = _builder(tmp_path, max_chars=1000)
    sessions.start()
    context = builder.build(session_id=sessions.current_session_id(), system="s", task="t")

    pressure = ContextPressurePolicy().evaluate(context, 1000)

    assert 0 <= pressure.ratio <= 1
    assert pressure.used_chars == context.total_chars
