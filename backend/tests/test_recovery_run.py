"""Run recovery: continue after the program restarted (M6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import AgentLoop, Checkpoint, CheckpointStore, LoopLimits, ScriptedModel
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.recovery import RunRecovery
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry


@pytest.fixture()
def env(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("content", encoding="utf-8")
    paths = AppPaths(
        project_root=project,
        state_dir=project,
        project_state_file=project / "project_state.json",
        memory_file=project / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(working_dir=project, store=store)
    executor = Executor(build_default_registry(context), context)
    sessions = SessionManager(project / "state" / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    checkpoints = CheckpointStore(project / "state" / "checkpoints")
    return project, executor, sessions, builder, checkpoints


def call(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


def test_no_checkpoints_means_nothing_to_recover(env) -> None:
    _project, _executor, sessions, _builder, checkpoints = env
    recovery = RunRecovery(checkpoints, sessions)

    assert recovery.plan() is None
    assert recovery.pending() == []

    result, report = recovery.resume(loop=None)
    assert result is None
    assert report.outcome == "not_needed"


def test_a_finished_run_is_not_resumed(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    loop = AgentLoop(
        ScriptedModel([call("read_file", path="a.txt"), "done"]),
        executor,
        sessions,
        builder=builder,
        checkpoints=checkpoints,
        limits=LoopLimits(max_steps=5),
    )
    loop.run("read it", run_id="finished")

    recovery = RunRecovery(checkpoints, sessions)
    plan = recovery.plan("finished")

    assert plan is not None
    assert plan.resumable is False
    assert "finished" in plan.reason
    assert recovery.pending() == []


def test_an_unfinished_run_is_listed(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    loop = AgentLoop(
        ScriptedModel([call("read_file", path="a.txt")]),
        executor,
        sessions,
        builder=builder,
        checkpoints=checkpoints,
        limits=LoopLimits(max_steps=1),
    )
    loop.run("unfinished task", run_id="pending-run")

    plan = RunRecovery(checkpoints, sessions).plan("pending-run")

    assert plan is not None
    assert plan.resumable is True
    assert plan.task == "unfinished task"
    assert plan.step == 1
    assert plan.session_id


def test_resume_continues_the_run(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    first = AgentLoop(
        ScriptedModel([call("read_file", path="a.txt")]),
        executor,
        sessions,
        builder=builder,
        checkpoints=checkpoints,
        limits=LoopLimits(max_steps=1),
    )
    first.run("finish the job", run_id="resume-me")

    # a new process builds a new loop
    resumed_model = ScriptedModel([call("read_file", path="a.txt"), "completed after restart"])
    second = AgentLoop(
        resumed_model,
        executor,
        sessions,
        builder=builder,
        checkpoints=checkpoints,
        limits=LoopLimits(max_steps=3),
    )
    resumed_model.restore({"index": 1})

    result, report = RunRecovery(checkpoints, sessions).resume(second, run_id="resume-me")

    assert report.recovered is True
    assert result.status == "completed"
    assert "completed after restart" in result.final_message
    actions = report.notes()
    assert any("found checkpoint" in action for action in actions)
    assert any("restored session" in action for action in actions)
    assert any("continued the run" in action for action in actions)


def test_resume_without_a_checkpoint_reports_cleanly(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    loop = AgentLoop(ScriptedModel(["x"]), executor, sessions, builder=builder, checkpoints=checkpoints)

    result, report = RunRecovery(checkpoints, sessions).resume(loop, run_id="never-existed")

    assert result is None
    assert report.outcome == "not_needed"
    assert "no checkpoint" in report.message


def test_a_missing_transcript_is_reported_but_still_recoverable(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    loop = AgentLoop(
        ScriptedModel([call("read_file", path="a.txt")]),
        executor,
        sessions,
        builder=builder,
        checkpoints=checkpoints,
        limits=LoopLimits(max_steps=1),
    )
    loop.run("a task", run_id="orphan")
    checkpoints.save(
        Checkpoint(
            run_id="orphan",
            task="a task",
            system="s",
            session_id="session-that-does-not-exist",
            step=1,
        )
    )

    plan = RunRecovery(checkpoints, sessions).plan("orphan")

    assert plan.resumable is True
    assert "transcript is missing" in plan.reason


def test_latest_picks_the_newest_unfinished_run(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    for run_id in ("older", "newer"):
        AgentLoop(
            ScriptedModel([call("read_file", path="a.txt")]),
            executor,
            sessions,
            builder=builder,
            checkpoints=checkpoints,
            limits=LoopLimits(max_steps=1),
        ).run("task " + run_id, run_id=run_id)

    plan = RunRecovery(checkpoints, sessions).plan()

    assert plan is not None
    assert plan.run_id == "newer"


def test_pending_lists_every_unfinished_run(env) -> None:
    _project, executor, sessions, builder, checkpoints = env
    for run_id in ("one", "two"):
        AgentLoop(
            ScriptedModel([call("read_file", path="a.txt")]),
            executor,
            sessions,
            builder=builder,
            checkpoints=checkpoints,
            limits=LoopLimits(max_steps=1),
        ).run("task", run_id=run_id)

    pending = RunRecovery(checkpoints, sessions).pending()

    assert {plan.run_id for plan in pending} == {"one", "two"}
