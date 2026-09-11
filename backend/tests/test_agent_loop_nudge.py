"""M12: one bounded nudge before a repeated call ends the run.

Observed live: a web model answered three times with the same run_shell while the
traceback sat in its context. Loop detection ended the run, correctly, but the
project stayed unfinished. Repeating a call that already returned this exact
result cannot change anything, so the loop now SAYS that in the next prompt once
before it gives up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import AgentLoop, CallableModel, CheckpointStore, LoopLimits
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry


def call(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def env(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    paths = AppPaths(
        project_root=project,
        state_dir=project,
        project_state_file=project / "project_state.json",
        memory_file=project / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(working_dir=project, store=store)
    executor = Executor(
        build_default_registry(context), context, log_path=project / "runs" / "log.jsonl"
    )
    sessions = SessionManager(project / "state" / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    return project, executor, sessions, builder


def run(env, decide, **limits):
    project, executor, sessions, builder = env
    loop = AgentLoop(
        CallableModel(decide),
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(
            max_steps=limits.pop("max_steps", 8),
            repeat_threshold=limits.pop("repeat_threshold", 2),
            max_loop_nudges=limits.pop("max_loop_nudges", 1),
            timeout_ms=60_000,
        ),
        checkpoints=CheckpointStore(env[0] / "state" / "checkpoints"),
        confirm=lambda request: "once",
    )
    return loop.run("read the same file forever")


def test_the_model_is_told_once_before_the_run_gives_up(env) -> None:
    prompts: list[str] = []

    def decide(prompt: str, system: str | None) -> str:
        prompts.append(prompt)
        return call("read_file", path="ghost.txt")

    result = run(env, decide)

    assert any("LOOP WARNING" in prompt for prompt in prompts), "the model was never told"
    assert result.status == "loop", result.reason
    nudges = [event for event in result.events if event.data.get("nudge")]
    assert len(nudges) == 1, "exactly one bounded nudge"


def test_the_model_can_recover_after_the_nudge(env) -> None:
    """A model that takes the hint finishes instead of being cut off."""
    state = {"seen": 0}

    def decide(prompt: str, system: str | None) -> str:
        if "LOOP WARNING" in prompt:
            return "I cannot make progress on that file; stopping here."
        state["seen"] += 1
        return call("read_file", path="ghost.txt")

    result = run(env, decide)

    assert result.status == "completed", result.reason
    assert "stopping here" in result.final_message
    assert state["seen"] >= 2, "it really did repeat before the nudge"


def test_no_nudge_when_the_budget_is_zero(env) -> None:
    prompts: list[str] = []

    def decide(prompt: str, system: str | None) -> str:
        prompts.append(prompt)
        return call("read_file", path="ghost.txt")

    result = run(env, decide, max_loop_nudges=0)

    assert result.status == "loop"
    assert not any("LOOP WARNING" in prompt for prompt in prompts)


def test_the_nudge_is_recorded_in_the_step(env) -> None:
    result = run(env, lambda prompt, system: call("read_file", path="ghost.txt"))
    nudged = [step for step in result.steps if step.note.startswith("loop nudge")]
    assert nudged, "the step that nudged the model says so"
