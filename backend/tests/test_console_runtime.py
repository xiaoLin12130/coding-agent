"""AgentRuntime tests: start, events, stop, confirmation, history (M8)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.agents import CallableModel
from app.config import AppPaths
from app.context import SessionManager
from app.runtime import AgentRuntime
from app.settings import Settings, SettingsStore
from app.storage import StateStore

BROKEN = "def add(a, b):" + chr(10) + "    return a - b" + chr(10)


def tool(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "calc.py").write_text(BROKEN, encoding="utf-8")
    monkeypatch.setenv("CODING_AGENT_STATE_DIR", str(project))
    monkeypatch.setenv("CODING_AGENT_RUNS_DIR", str(project / "runs"))

    store = StateStore()
    sessions = SessionManager(project / "state" / "sessions", store=store)
    settings = SettingsStore(project / "state" / "settings.json")
    current = settings.load()
    current.working_dir = str(project)
    settings.save(current)
    return project, sessions, settings


def make_runtime(env, replies, **kwargs) -> AgentRuntime:
    _project, sessions, settings = env
    holder: dict = {"n": 0}

    def decide(prompt: str, system: str | None) -> str:
        index = holder["n"]
        holder["n"] += 1
        if index >= len(replies):
            return "done"
        return replies[index]

    runtime = AgentRuntime(
        sessions, settings, model_factory=lambda: CallableModel(decide)
    )
    RuntimeProbe.last = runtime
    return runtime


class RuntimeProbe:
    last: AgentRuntime | None = None


# --- lifecycle -------------------------------------------------------------


def test_a_run_reaches_completion_and_records_events(env) -> None:
    project, _sessions, _settings = env
    runtime = make_runtime(
        env,
        [
            tool("read_file", path="src/calc.py"),
            tool("write_file", path="src/calc.py", content="def add(a, b):" + chr(10) + "    return a + b" + chr(10)),
            "all done",
        ],
    )

    record = runtime.start("fix add()")
    assert record.run_id
    assert runtime.wait(timeout=20) is True

    assert runtime.running is False
    assert record.status == "completed", record.reason
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8").endswith(
        "return a + b" + chr(10)
    )

    types = [event.type for event in runtime.events()]
    for expected in ("run_start", "step_start", "model_reply", "tool_result", "run_end"):
        assert expected in types, expected


def test_history_keeps_finished_runs(env) -> None:
    runtime = make_runtime(env, ["nothing to do"])

    runtime.start("a task")
    runtime.wait(timeout=20)

    history = runtime.history()
    assert len(history) == 1
    assert history[0].task == "a task"
    assert history[0].status == "completed"


def test_an_empty_task_is_refused(env) -> None:
    runtime = make_runtime(env, [])

    with pytest.raises(ValueError):
        runtime.start("   ")


def test_an_unknown_mode_is_refused(env) -> None:
    runtime = make_runtime(env, [])

    with pytest.raises(ValueError):
        runtime.start("task", mode="swarm")


def test_a_second_run_while_one_is_going_is_refused(env) -> None:
    gate = threading.Event()

    def blocking(prompt: str, system: str | None) -> str:
        gate.wait(timeout=10)
        return "done"

    _project, sessions, settings = env
    runtime = AgentRuntime(sessions, settings, model_factory=lambda: CallableModel(blocking))
    runtime.start("first")

    try:
        with pytest.raises(RuntimeError):
            runtime.start("second")
    finally:
        gate.set()
        runtime.wait(timeout=20)


def test_a_missing_model_reports_an_error_instead_of_hanging(env) -> None:
    _project, sessions, settings = env
    runtime = AgentRuntime(sessions, settings)  # no model_factory

    runtime.start("a task")
    assert runtime.wait(timeout=20) is True

    record = runtime.record()
    assert record is not None
    assert record.status == "error"
    assert "model" in record.reason.lower()


# --- stop ------------------------------------------------------------------


def test_stop_ends_the_run(env) -> None:
    _project, sessions, settings = env
    state = {"n": 0}

    def slow(prompt: str, system: str | None) -> str:
        state["n"] += 1
        time.sleep(0.05)
        return tool("list_dir", path=".")

    runtime = AgentRuntime(sessions, settings, model_factory=lambda: CallableModel(slow))
    record = runtime.start("loop forever", max_steps=200)

    # let it take a step or two, then stop it
    deadline = time.time() + 5
    while state["n"] < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert runtime.stop() is True
    assert runtime.wait(timeout=20) is True

    assert record.status == "interrupted"


def test_stop_without_a_run_is_a_no_op(env) -> None:
    runtime = make_runtime(env, [])

    assert runtime.stop() is False
    assert runtime.stop("some-run") is False


def test_stop_ignores_a_mismatched_run_id(env) -> None:
    gate = threading.Event()

    def blocking(prompt: str, system: str | None) -> str:
        gate.wait(timeout=10)
        return "done"

    _project, sessions, settings = env
    runtime = AgentRuntime(sessions, settings, model_factory=lambda: CallableModel(blocking))
    record = runtime.start("a task")

    try:
        assert runtime.stop("not-this-run") is False
        assert runtime.running is True
    finally:
        gate.set()
        runtime.wait(timeout=20)
    assert record.status in ("completed", "interrupted")


# --- confirmation ----------------------------------------------------------


def test_a_confirmation_is_published_and_can_be_answered(env) -> None:
    _project, sessions, settings = env
    current = settings.load()
    current.confirmation.policy = "ask"
    settings.save(current)

    runtime = make_runtime(
        env,
        [tool("run_shell", command="echo hi"), "ran it"],
    )
    record = runtime.start("run a command")

    # wait for the confirmation to be published
    deadline = time.time() + 10
    request = None
    while time.time() < deadline:
        request = runtime.pending_confirmation()
        if request is not None:
            break
        time.sleep(0.02)

    assert request is not None, "the confirmation was published"
    assert request["tool"] == "run_shell"
    assert "command" in request

    # answer it, and only then does the run continue
    assert runtime.confirm(request["request_id"], "once") is True
    assert runtime.wait(timeout=20) is True

    assert record.status == "completed", record.reason
    assert any(event.type == "confirm_request" for event in runtime.events())


def test_an_unknown_confirmation_id_is_refused(env) -> None:
    runtime = make_runtime(env, [])

    assert runtime.confirm("nope", "once") is False
    assert runtime.confirm("nope", "maybe") is False


def test_the_deny_policy_rejects_high_risk_calls(env) -> None:
    _project, sessions, settings = env
    current = settings.load()
    current.confirmation.policy = "deny"
    settings.save(current)

    runtime = make_runtime(env, [tool("run_shell", command="echo hi"), "could not run it"])
    record = runtime.start("run a command")
    assert runtime.wait(timeout=20) is True

    assert record.status == "completed"
    results = [event for event in runtime.events() if event.type == "tool_result"]
    assert results and results[0].ok is False


# --- the multi-agent mode --------------------------------------------------


def test_the_multi_agent_mode_runs_the_roles(env) -> None:
    _project, sessions, settings = env
    current = settings.load()
    current.multi_agent.max_rounds = 1
    current.confirmation.policy = "once"
    settings.save(current)

    from app.agents.roles import DEFAULT_ROLES

    replies: list[str] = []
    # planner, guard, coder, reviewer, keeper, curator
    replies.append("1. do the thing")
    replies.append("VERDICT: SAFE")
    replies.append("implemented it")
    replies.append("VERDICT: APPROVED")
    replies.append("state recorded")
    replies.append("nothing to remember")

    runtime = make_runtime(env, replies)
    record = runtime.start("do the thing", mode="multi")
    assert runtime.wait(timeout=30) is True

    assert record.mode == "multi"
    assert record.status == "completed", record.reason
    assert record.round_count == 1
    assert len(DEFAULT_ROLES) == 6


# --- events ----------------------------------------------------------------


def test_subscribers_receive_events(env) -> None:
    runtime = make_runtime(env, ["done"])
    seen: list[str] = []
    unsubscribe = runtime.subscribe(lambda event: seen.append(event.type))

    runtime.start("a task")
    runtime.wait(timeout=20)
    unsubscribe()

    assert "run_start" in seen
    assert "run_end" in seen


def test_a_broken_subscriber_does_not_break_the_run(env) -> None:
    runtime = make_runtime(env, ["done"])

    def explode(event) -> None:
        raise RuntimeError("subscriber is broken")

    runtime.subscribe(explode)

    runtime.start("a task")
    assert runtime.wait(timeout=20) is True
    assert runtime.record().status == "completed"


def test_roles_are_published_for_the_console() -> None:
    roles = AgentRuntime.roles()

    assert len(roles) == 6
    planner = next(role for role in roles if role["name"] == "planner")
    assert "write_file" not in planner["allowed_tools"]
