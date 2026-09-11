"""M6 acceptance: the task continues after each documented failure.

docs/M6:

    Browser crash / WebSocket disconnect / Login expired / 程序重启 /
    Context 达到阈值  ->  the task can continue

Each scenario below drives the real components (loop, sessions, checkpoints,
browser) and asserts that the work carries on rather than restarting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import AgentLoop, CheckpointStore, LoopLimits, ScriptedModel
from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.web_chat import WebChatProvider
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.context.models import ContextBudget
from app.recovery import (
    BrowserRecovery,
    ContextThresholds,
    RunRecovery,
    SessionRecovery,
    build_snapshot,
)
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry


def call(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def workspace(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("value = 1" + chr(10), encoding="utf-8")
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
    return project, store, executor, sessions, builder, checkpoints


def make_loop(workspace, replies, **kwargs) -> AgentLoop:
    _project, _store, executor, sessions, builder, checkpoints = workspace
    limits = kwargs.pop("limits", None) or LoopLimits(max_steps=kwargs.pop("max_steps", 5))
    return AgentLoop(
        ScriptedModel(replies, final_message=kwargs.pop("final", "Done.")),
        executor,
        sessions,
        builder=builder,
        limits=limits,
        checkpoints=checkpoints,
        **kwargs,
    )


# --- 1. 程序重启 (program restart) ----------------------------------------


def test_program_restart_continues_the_run(workspace) -> None:
    project, _store, executor, sessions, builder, checkpoints = workspace

    # run 1: stopped by its budget, leaving a checkpoint behind
    stopped = make_loop(
        workspace, [call("read_file", path="src/app.py")], max_steps=1
    ).run("update src/app.py", run_id="restart-run")
    assert stopped.status == "max_steps"

    # the program closes; a new process builds everything again
    fresh_store = StateStore(
        AppPaths(
            project_root=project,
            state_dir=project,
            project_state_file=project / "project_state.json",
            memory_file=project / "memory.json",
        )
    )
    fresh_sessions = SessionManager(project / "state" / "sessions", store=fresh_store)
    fresh_builder = ContextBuilder(
        fresh_sessions.transcript, fresh_sessions.memory, fresh_sessions.store
    )
    fresh_executor = Executor(
        build_default_registry(ToolContext(working_dir=project, store=fresh_store)),
        ToolContext(working_dir=project, store=fresh_store),
    )
    # A real LLM has no restorable script state, so a resumed run must derive
    # its next move from the checkpoint and the transcript, not from a rewind.
    # CallableModel models that honestly: its restore() is a no-op.
    from app.agents import CallableModel

    steps = {"n": 0}

    def decide(prompt: str, system: str | None) -> str:
        steps["n"] += 1
        if steps["n"] == 1:
            return call("write_file", path="src/app.py", content="value = 2" + chr(10))
        return "updated after the restart"

    model = CallableModel(decide)
    loop = AgentLoop(
        model,
        fresh_executor,
        fresh_sessions,
        builder=fresh_builder,
        limits=LoopLimits(max_steps=3),
        checkpoints=CheckpointStore(project / "state" / "checkpoints"),
    )

    result, report = RunRecovery(
        CheckpointStore(project / "state" / "checkpoints"), fresh_sessions
    ).resume(loop, run_id="restart-run")

    assert report.recovered is True
    assert result.status == "completed"
    assert project.joinpath("src", "app.py").read_text(encoding="utf-8") == "value = 2" + chr(10)
    # the transcript from before the restart is still there
    assert any(
        entry.content == "update src/app.py"
        for entry in fresh_sessions.transcript.read(fresh_sessions.current_session_id())
    )


# --- 2. Context 达到阈值 (threshold) --------------------------------------


def test_hitting_the_hard_threshold_rotates_and_continues(workspace) -> None:
    project, _store, executor, sessions, builder, checkpoints = workspace
    # a tiny budget makes the threshold reachable in a few steps
    builder.budget = ContextBudget(max_chars=900, min_section_chars=40)
    sessions.save_project_state(
        __import__("app.models", fromlist=["ProjectState"]).ProjectState(
            current_milestone="M6", current_task="keep editing the file"
        )
    )
    filler = "padding " * 40

    replies = [
        call("read_file", path="src/app.py"),
        call("write_file", path="src/app.py", content=filler),
        call("read_file", path="src/app.py"),
        call("write_file", path="src/app.py", content=filler + "more "),
        call("read_file", path="src/app.py"),
        "finished after the rotation",
    ]
    loop = make_loop(
        workspace,
        replies,
        limits=LoopLimits(max_steps=8, timeout_ms=60_000, repeat_threshold=9),
        thresholds=ContextThresholds(soft_ratio=0.5, hard_ratio=0.7),
    )

    result = loop.run("keep editing the file")

    rotations = [event for event in result.events if event.type == "context_rotated"]
    assert rotations, "the hard threshold should have rotated the session"
    assert rotations[0].ok is True
    assert result.status == "completed", result.reason

    # the archived session is on disk and the new one carries the task
    archived = sessions.archived_sessions()
    assert archived, "the old session was archived"
    assert Path(archived[0].archive_path).exists()
    new_id = rotations[0].data["new_session_id"]
    seed = sessions.transcript.read(new_id)[0]
    assert seed.meta["kind"] == "session_seed"
    assert "keep editing the file" in seed.content
    assert "current_milestone: M6" in seed.content


def test_soft_threshold_compacts_without_losing_the_session(workspace) -> None:
    _project, _store, executor, sessions, builder, checkpoints = workspace
    # Room to spare, so the measured ratio lands between the two thresholds.
    builder.budget = ContextBudget(max_chars=40_000, min_section_chars=40)
    for number in range(6):
        sessions.record("user", "message " + str(number) + " " + "x" * 120)
        sessions.record("assistant", "reply " + str(number) + " " + "y" * 120)

    # Measure first, then place the soft threshold just under it, so the test
    # asserts the policy rather than guessing at a size.
    measured = SessionRecovery(sessions, builder).evaluate(
        sessions.current_session_id() or "", system="s", task="keep going"
    )
    assert measured.level != "hard", "the fixture must sit below the hard line"
    loop = make_loop(
        workspace,
        ["nothing to do"],
        limits=LoopLimits(max_steps=2),
        thresholds=ContextThresholds(
            soft_ratio=max(measured.ratio * 0.5, 0.01), hard_ratio=0.99
        ),
    )
    before_session = sessions.current_session_id()

    result = loop.run("keep going")

    pressures = [event for event in result.events if event.type == "context_pressure"]
    assert pressures, "the soft threshold should have been reported"
    assert sessions.current_session_id() == before_session, "soft pressure keeps the session"
    assert result.status == "completed"


# --- 3. WebSocket disconnect ----------------------------------------------


def test_a_reconnecting_client_can_resync_everything(workspace) -> None:
    """The server keeps no essential state in memory, so a reconnect re-reads it."""
    project, store, _executor, sessions, builder, checkpoints = workspace
    sessions.start()
    sessions.record("user", "a question from before the disconnect")
    sessions.record("assistant", "an answer from before the disconnect")

    # a brand-new manager, as a different request/process would build
    fresh = SessionManager(project / "state" / "sessions", store=store)
    snapshot = build_snapshot(
        sessions=fresh,
        checkpoints=checkpoints,
        system="s",
        task="carry on after the reconnect",
    )

    assert snapshot.active_session_id == sessions.current_session_id()
    assert snapshot.session_message_count == 2
    assert snapshot.context_pressure is not None
    assert snapshot.context_pressure.level in ("ok", "soft", "hard")

    entries = fresh.transcript.read(snapshot.active_session_id or "")
    assert [entry.content for entry in entries] == [
        "a question from before the disconnect",
        "an answer from before the disconnect",
    ]


def test_a_reconnect_also_reports_a_pending_run(workspace) -> None:
    project, store, executor, sessions, builder, checkpoints = workspace
    make_loop(
        workspace, [call("read_file", path="src/app.py")], max_steps=1
    ).run("an unfinished task", run_id="ws-run")

    snapshot = build_snapshot(
        sessions=SessionManager(project / "state" / "sessions", store=store),
        checkpoints=checkpoints,
    )

    assert snapshot.latest_run is not None
    assert snapshot.latest_run.run_id == "ws-run"
    assert snapshot.latest_run.resumable is True


# --- 4. Browser crash ------------------------------------------------------


def _browser_factory(tmp_path: Path, profile):
    def factory():
        driver = BrowserDriver(
            profile_dir=tmp_path / "browser-profile",
            artifacts=ArtifactStore(base_dir=tmp_path / "runs", run_name="recovery"),
        ).start()
        provider = WebChatProvider(driver, profile)
        session = type("Session", (), {})()
        session.driver = driver
        session.provider = provider
        session.close = driver.close
        return session

    return factory


def test_browser_crash_mid_task_is_recovered_and_the_task_continues(
    tmp_path: Path, workspace, fixture_site, mock_profile
) -> None:
    project, _store, executor, sessions, builder, checkpoints = workspace
    recovery = BrowserRecovery(_browser_factory(tmp_path, mock_profile), max_restarts=1)

    try:
        from app.agents import BrowserModel

        # the factory form is what lets the model follow a restarted page
        model = BrowserModel(provider_factory=lambda: recovery.session.provider)
        recovery.session.provider.open()

        crashes = {"n": 0}

        def on_model_failure(exc: Exception) -> bool:
            """The loop asks this when the model call dies."""
            crashes["n"] += 1
            if crashes["n"] > 1:
                return False
            remaining = project / "crashed.txt"
            remaining.write_text("the page died", encoding="utf-8")
            report = recovery.ensure_ready()
            return report.recovered

        loop = AgentLoop(
            model,
            executor,
            sessions,
            builder=builder,
            limits=LoopLimits(max_steps=2, timeout_ms=180_000),
            checkpoints=checkpoints,
            system="Answer briefly.",
            on_model_failure=on_model_failure,
        )

        # crash the page BEFORE the loop asks, so the first call fails
        recovery.session.driver.close()

        result = loop.run("say something after the crash")

        assert crashes["n"] == 1, "the loop asked for recovery exactly once"
        assert any(event.type == "model_recovered" for event in result.events)
        assert result.status in ("completed", "max_steps"), result.reason
        replies = [event for event in result.events if event.type == "model_reply"]
        assert replies, "the restarted page answered"
        assert "Fixture reply" in replies[0].message
    finally:
        recovery.close()


# --- 5. Login expired ------------------------------------------------------


def test_login_expiry_is_recovered_and_the_task_continues(
    tmp_path: Path, workspace, fixture_site, mock_profile
) -> None:
    project, _store, executor, sessions, builder, checkpoints = workspace
    profile = mock_profile.model_copy(
        update={
            "url": mock_profile.url + "?login=1",
            "ready_selector": "#login-wall, #composer",
        }
    )
    recovery = BrowserRecovery(
        _browser_factory(tmp_path, profile), login_timeout_ms=10_000
    )

    try:
        from app.agents import BrowserModel

        session = recovery.session
        session.provider.open()
        assert session.provider.is_logged_in() is False

        model = BrowserModel(provider_factory=lambda: recovery.session.provider)
        recoveries = {"n": 0}

        def on_model_failure(exc: Exception) -> bool:
            recoveries["n"] += 1
            if recoveries["n"] > 1:
                return False
            # the human signs in inside the headed window
            session.driver.page.evaluate(
                "() => window.setTimeout("
                "() => document.getElementById('login-button').click(), 600)"
            )
            report = recovery.ensure_logged_in(timeout_ms=10_000)
            return report.recovered

        loop = AgentLoop(
            model,
            executor,
            sessions,
            builder=builder,
            limits=LoopLimits(max_steps=2, timeout_ms=180_000),
            checkpoints=checkpoints,
            system="Answer briefly.",
            on_model_failure=on_model_failure,
        )

        result = loop.run("continue after the login expired")

        assert recoveries["n"] == 1
        assert session.provider.is_logged_in() is True
        replies = [event for event in result.events if event.type == "model_reply"]
        assert replies, "the page answered once the login was restored"
    finally:
        recovery.close()


# --- the sequence itself ---------------------------------------------------


def test_the_documented_sequence_runs_in_order(workspace) -> None:
    """完成当前 turn -> 保存 State -> 摘要 Transcript -> 新建 Session -> 恢复任务"""
    project, store, _executor, sessions, builder, _checkpoints = workspace
    sessions.start()
    for number in range(1, 5):
        sessions.record("user", "question " + str(number))
        sessions.record("assistant", "answer " + str(number))
    sessions.save_project_state(
        __import__("app.models", fromlist=["ProjectState"]).ProjectState(
            current_milestone="M6", current_task="finish the recovery layer"
        )
    )

    report = SessionRecovery(sessions, builder).rotate(reason="context_budget")

    actions = report.notes()
    ordered = [
        action
        for action in actions
        if action.startswith(("saved", "project state", "summarised", "archived", "opened", "injected"))
    ]
    assert ordered[0].startswith(("saved", "project state"))
    assert ordered[1].startswith("summarised")
    assert ordered[2].startswith("archived")
    assert ordered[3].startswith("opened")
    assert any(action.startswith("injected project state") for action in ordered)
    assert any(action.startswith("injected memory") for action in ordered)
    assert report.recovered is True
