"""M5 acceptance: a simple coding task end to end.

docs/M5 requires:

    读文件 -> 修改文件 -> 运行测试 -> 根据结果继续 -> 完成任务

The model here is a function rather than a fixed script, because "根据结果继续"
means the next action must depend on what the previous tool returned. It reads
the assembled prompt — the same context the loop sends — and decides.

The project ships a real check script, so "运行测试" runs real code against the
real module and its output is what drives the next decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import (
    AgentLoop,
    CallableModel,
    CheckpointStore,
    LoopLimits,
)
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry

BROKEN = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"

# The check compiles calc.py from source instead of importing it: an in-place
# rewrite that keeps the byte size and lands inside the same mtime second can
# leave a stale __pycache__ entry, and the check would then report the previous
# revision. (Real-world hazard, not a loop bug - see the note in project state.)
CHECK = '''"""Runs the real module and reports one test result."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "calc.py").read_text(encoding="utf-8")

namespace = {}
exec(compile(SOURCE, str(ROOT / "src" / "calc.py"), "exec"), namespace)
add = namespace["add"]

if add(2, 3) == 5:
    print("1 passed")
    raise SystemExit(0)

print("1 failed: add(2, 3) returned " + str(add(2, 3)))
raise SystemExit(1)
'''


def tool_call(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text(BROKEN, encoding="utf-8")
    (root / "tests" / "check.py").write_text(CHECK, encoding="utf-8")
    return root


@pytest.fixture()
def loop_env(project: Path):
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


def make_loop(env, decide, **limits) -> AgentLoop:
    _project, executor, sessions, builder = env
    return AgentLoop(
        CallableModel(decide),
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(
            max_steps=limits.pop("max_steps", 10),
            timeout_ms=limits.pop("timeout_ms", 120_000),
            repeat_threshold=limits.pop("repeat_threshold", 5),
        ),
        checkpoints=CheckpointStore(env[0] / "state" / "checkpoints"),
        confirm=limits.pop("confirm", lambda request: "once"),
    )


# --- the acceptance path --------------------------------------------------


def test_coding_task_read_patch_test_react_complete(loop_env) -> None:
    project = loop_env[0]

    def decide(prompt: str, system: str | None) -> str:
        if "tool read_file -> ok" not in prompt:
            return tool_call("read_file", path="src/calc.py")
        if "return a + b" not in prompt:
            return tool_call(
                "apply_patch",
                path="src/calc.py",
                hunks=[{"old": "return a - b", "new": "return a + b"}],
            )
        if "tool run_shell -> ok" not in prompt:
            return tool_call("run_shell", command="python tests/check.py")
        if "1 passed" in prompt:
            return "Fixed add(): it now sums instead of subtracting, and the check passes."
        return tool_call("run_shell", command="python tests/check.py")

    result = make_loop(loop_env, decide).run(
        "add(2,3) returns -1; find and fix the bug, then run the check"
    )

    assert result.status == "completed", result.reason
    assert list(result.tool_summary()) == ["read_file", "apply_patch", "run_shell"]
    assert result.tool_failures == 0
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") == FIXED
    assert "sums" in result.final_message

    shell_events = [e for e in result.events if e.tool == "run_shell" and e.type == "tool_result"]
    assert any("1 passed" in event.message for event in shell_events), "the check really ran"


def test_the_model_reacts_to_a_failing_check_and_corrects_itself(loop_env) -> None:
    """根据结果继续: the corrective patch is chosen only after seeing the failure.

    The model is a phase machine, so each step's decision is deliberate; the
    assertions inside it record exactly what the loop showed the model.
    """
    project = loop_env[0]
    seen: dict[str, str] = {}
    phase = {"n": 0}

    def decide(prompt: str, system: str | None) -> str:
        phase["n"] += 1
        step = phase["n"]
        if step == 1:
            return tool_call("read_file", path="src/calc.py")
        if step == 2:
            # Deliberately wrong first attempt.
            return tool_call(
                "apply_patch",
                path="src/calc.py",
                hunks=[{"old": "return a - b", "new": "return a * b"}],
            )
        if step == 3:
            return tool_call("run_shell", command="python tests/check.py")
        if step == 4:
            # This branch is only correct if the previous result was visible.
            seen["failure"] = prompt
            return tool_call(
                "apply_patch",
                path="src/calc.py",
                hunks=[{"old": "return a * b", "new": "return a + b"}],
            )
        if step == 5:
            return tool_call("run_shell", command="python tests/check.py")
        seen["success"] = prompt
        return "Corrected after seeing the failing check; it passes now."

    result = make_loop(loop_env, decide).run("make the check pass")

    # the model was shown the failure, and its correction came from that
    assert "1 failed" in seen["failure"], "the failing output never reached the model"
    assert "returned 6" in seen["failure"]
    assert "1 passed" in seen["success"], "the passing output never reached the model"

    assert result.status == "completed", result.reason
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") == FIXED
    assert result.tool_summary()["apply_patch"] == 2, "the wrong patch was corrected"


def test_the_loop_stops_when_the_same_blocked_call_repeats(loop_env) -> None:
    """The loop cannot be talked into leaving the project."""
    project = loop_env[0]
    outside = project.parent / "secrets.txt"
    outside.write_text("SECRET", encoding="utf-8")

    result = make_loop(
        loop_env,
        lambda prompt, system: tool_call("read_file", path=str(outside)),
        repeat_threshold=2,
    ).run("read the file outside the project")

    assert result.status == "loop"
    assert result.tool_failures >= 1
    assert not any("SECRET" in event.message for event in result.events)


def test_an_unattended_run_reports_the_refusal_instead_of_running(loop_env) -> None:
    """No confirmation hook: a high-risk command is refused, not executed."""
    project = loop_env[0]
    marker = project / "should-not-exist.txt"

    def decide(prompt: str, system: str | None) -> str:
        if "confirmation_required" in prompt:
            return "I cannot run that without approval."
        return tool_call(
            "run_shell",
            command="python -c \"open('should-not-exist.txt','w').write('x')\"",
        )

    result = make_loop(loop_env, decide, confirm=None).run("run a high-risk command")

    assert result.status == "completed"
    assert result.tool_failures == 1
    assert not marker.exists()


def test_the_loop_leaves_an_audit_trail(loop_env) -> None:
    project, _executor, sessions, _builder = loop_env

    def decide(prompt: str, system: str | None) -> str:
        if "tool read_file -> ok" not in prompt:
            return tool_call("read_file", path="src/calc.py")
        return "read it"

    result = make_loop(loop_env, decide).run("read the file")

    log = project / "runs" / "log.jsonl"
    assert log.exists()
    record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert record["name"] == "read_file"

    entries = sessions.transcript.read(sessions.current_session_id())
    assert [entry.role for entry in entries] == ["user", "assistant", "tool", "assistant"]
    assert entries[2].tool_name == "read_file"

    assert Path(result.checkpoint_path).exists()


def test_a_run_survives_a_crash_and_continues(loop_env) -> None:
    """Checkpoint + resume: the M5 groundwork M6 builds the recovery flow on."""
    project, executor, sessions, builder = loop_env
    calls = {"n": 0}

    def crashing_model(prompt: str, system: str | None) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return tool_call("read_file", path="src/calc.py")
        raise KeyboardInterrupt("simulated crash")

    loop = AgentLoop(
        CallableModel(crashing_model),
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(max_steps=5, timeout_ms=30_000),
        checkpoints=CheckpointStore(project / "state" / "checkpoints"),
    )
    run_id = "crash-run"
    try:
        loop.run("inspect and fix", run_id=run_id)
    except KeyboardInterrupt:
        pass

    store = CheckpointStore(project / "state" / "checkpoints")
    crashed = store.load(run_id)
    assert crashed is not None, "the crash left a checkpoint behind"
    assert crashed.step == 1
    assert crashed.task == "inspect and fix"

    # A new process continues the same run.
    resumed = AgentLoop(
        CallableModel(lambda prompt, system: "continued after the restart"),
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(max_steps=5, timeout_ms=30_000),
        checkpoints=CheckpointStore(project / "state" / "checkpoints"),
    )
    result = resumed.run("inspect and fix", run_id=run_id, resume=True)

    assert result.status == "completed"
    assert store.load(run_id).step == 2
    entries = sessions.transcript.read(sessions.current_session_id())
    assert any("src/calc.py" in entry.content for entry in entries), (
        "the pre-crash transcript is still in the session"
    )
