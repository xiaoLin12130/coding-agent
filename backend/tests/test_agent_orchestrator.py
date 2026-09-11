"""AgentOrchestrator tests: the collaboration and its four hard constraints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import (
    AgentOrchestrator,
    CallableModel,
    OrchestrationLimits,
)
from app.agents.roles import get_role
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.storage import StateStore
from app.tools import ToolContext, build_default_registry

BROKEN = "def add(a, b):" + chr(10) + "    return a - b" + chr(10)
FIXED = "def add(a, b):" + chr(10) + "    return a + b" + chr(10)
CHECK = (
    "import pathlib" + chr(10)
    + "ROOT = pathlib.Path(__file__).resolve().parents[1]" + chr(10)
    + "ns = {}" + chr(10)
    + "exec(compile((ROOT / 'src' / 'calc.py').read_text(encoding='utf-8'), 'calc.py', 'exec'), ns)" + chr(10)
    + "print('1 passed' if ns['add'](2, 3) == 5 else '1 failed')" + chr(10)
)


def tool(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def env(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "src" / "calc.py").write_text(BROKEN, encoding="utf-8")
    (project / "tests" / "check.py").write_text(CHECK, encoding="utf-8")
    paths = AppPaths(
        project_root=project,
        state_dir=project,
        project_state_file=project / "project_state.json",
        memory_file=project / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(working_dir=project, store=store)
    sessions = SessionManager(project / "state" / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    registry = build_default_registry(context)
    return project, store, context, sessions, builder, registry


def which_role(system: str) -> str:
    if "PLANNER" in system:
        return "planner"
    if "CODER" in system:
        return "coder"
    if "REVIEWER" in system:
        return "reviewer"
    if "SAFETY GUARD" in system:
        return "safety_guard"
    if "STATE KEEPER" in system:
        return "state_keeper"
    return "memory_curator"


def make(env, decide, **kwargs) -> AgentOrchestrator:
    _project, _store, context, sessions, builder, registry = env
    limits = kwargs.pop("limits", None) or OrchestrationLimits(
        max_rounds=kwargs.pop("max_rounds", 3), timeout_ms=kwargs.pop("timeout_ms", 60_000)
    )
    return AgentOrchestrator(
        CallableModel(lambda prompt, system: decide(which_role(system or ""), prompt, system or "")),
        sessions,
        context,
        builder=builder,
        limits=limits,
        registry=registry,
        confirm=kwargs.pop("confirm", lambda request: "once"),
    )


def happy_policy(role: str, prompt: str, system: str) -> str:
    if role == "planner":
        return "1. read src/calc.py" + chr(10) + "2. patch it" + chr(10) + "3. run the check"
    if role == "safety_guard":
        return "VERDICT: SAFE"
    if role == "coder":
        if "tool apply_patch -> ok" not in prompt:
            return tool(
                "apply_patch",
                path="src/calc.py",
                hunks=[{"old": "return a - b", "new": "return a + b"}],
            )
        if "tool run_shell -> ok" not in prompt:
            return tool("run_shell", command="python tests/check.py")
        return "patched add() and the check passes"
    if role == "reviewer":
        return "VERDICT: APPROVED" + chr(10) + "NOTES: verified"
    if role == "state_keeper":
        if "tool update_project_state -> ok" in prompt:
            return "state recorded"
        return tool("update_project_state", current_task="fix add()")
    return "nothing durable to remember"


# --- the acceptance path ---------------------------------------------------


def test_a_coding_task_is_completed_by_the_roles(env) -> None:
    project = env[0]

    result = make(env, happy_policy).run("fix add() so the check passes")

    assert result.status == "completed", result.reason
    assert result.round_count == 1
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") == FIXED
    # every role took part
    assert set(result.role_summary()) == {
        "planner",
        "safety_guard",
        "coder",
        "reviewer",
        "state_keeper",
        "memory_curator",
    }
    # the coder did the work through tools
    assert "apply_patch" in result.tools_by_role()["coder"]
    assert "run_shell" in result.tools_by_role()["coder"]


def test_the_plan_is_recorded(env) -> None:
    result = make(env, happy_policy).run("fix add()")

    assert "patch it" in result.plan


def test_the_state_keeper_records_the_outcome(env) -> None:
    project, store, _context, _sessions, _builder, _registry = env

    make(env, happy_policy).run("fix add()")

    assert store.load_project_state().current_task == "fix add()"


# --- the fix loop ----------------------------------------------------------


def test_a_rejected_round_sends_the_coder_back(env) -> None:
    """Reviewer -> NEEDS_FIX -> Coder -> Reviewer -> approved."""
    reviews = {"n": 0}

    def decide(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            reviews["n"] += 1
            if reviews["n"] == 1:
                return "VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: add() still subtracts"
            return "VERDICT: APPROVED"
        return happy_policy(role, prompt, system)

    result = make(env, decide).run("fix add()")

    assert result.status == "completed", result.reason
    assert result.round_count == 2
    assert result.rounds[0].verdict == "needs_fix"
    assert result.rounds[1].verdict == "approved"
    assert result.rounds[0].issues == ["add() still subtracts"]


def test_the_feedback_is_given_to_the_coder(env) -> None:
    """The reviewer's issues must reach the next Coder prompt, not be dropped."""
    tasks: list[str] = []
    reviews = {"n": 0}

    def decide(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            reviews["n"] += 1
            if reviews["n"] == 1:
                return "VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: the tests were never run"
            return "VERDICT: APPROVED"
        if role == "coder" and "## task" in prompt:
            # the task section is the coder prompt the orchestrator built
            tasks.append(prompt.split("## task", 1)[1])
        return happy_policy(role, prompt, system)

    make(env, decide).run("fix add()")

    assert len(tasks) >= 2, "the coder ran in two rounds"
    assert "the tests were never run" in tasks[-1]


# --- hard constraint: bounded ----------------------------------------------


def test_the_round_limit_stops_the_collaboration(env) -> None:
    def always_rejects(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            return "VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: still broken"
        return happy_policy(role, prompt, system)

    result = make(env, always_rejects, max_rounds=2).run("fix add()")

    # the same verdict twice also trips the stall guard, so either bound may win
    assert result.status in ("max_rounds", "stalled")
    assert result.round_count <= 2
    assert result.ok is False


def test_repeating_issues_stall_the_collaboration(env) -> None:
    """No infinite agent conversation: a repeated verdict stops it."""
    calls = {"n": 0}

    def always_rejects(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            calls["n"] += 1
            return "VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: always the same problem"
        return happy_policy(role, prompt, system)

    result = make(env, always_rejects, max_rounds=5).run("fix add()")

    assert result.status == "stalled"
    assert "always the same problem" in result.reason
    assert calls["n"] == 2, "it must stop at the stall threshold, not run every round"


def test_progress_resets_the_stall_counter(env) -> None:
    rounds = {"n": 0}

    def different_issues(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            rounds["n"] += 1
            if rounds["n"] >= 3:
                return "VERDICT: APPROVED"
            return "VERDICT: NEEDS_FIX" + chr(10) + "ISSUE: problem number " + str(rounds["n"])
        return happy_policy(role, prompt, system)

    result = make(env, different_issues, max_rounds=4).run("fix add()")

    assert result.status == "completed"
    assert result.round_count == 3


def test_the_time_budget_stops_the_collaboration(env) -> None:
    """A fake clock proves the bound without waiting in real time."""
    _project, _store, context, sessions, builder, registry = env
    # the first tick starts the run, the second is the round-boundary check
    ticks = iter([0.0, 99.0] + [99.0] * 50)
    orchestrator = AgentOrchestrator(
        CallableModel(
            lambda prompt, system: happy_policy(which_role(system or ""), prompt, system or "")
        ),
        sessions,
        context,
        builder=builder,
        limits=OrchestrationLimits(max_rounds=5, timeout_ms=1000),
        registry=registry,
        # without a confirmation hook the coder's shell call would be refused
        # and repeat until the loop guard fired, hiding the timeout
        confirm=lambda request: "once",
        clock=lambda: next(ticks),
    )

    result = orchestrator.run("fix add()")

    assert result.status == "timeout"
    assert "time budget" in result.reason
    assert result.round_count == 0, "no round may start after the deadline"


def test_each_role_has_its_own_step_budget(env) -> None:
    """A role cannot run forever inside one collaboration."""
    steps = {"coder": 0}

    def verbose_coder(role: str, prompt: str, system: str) -> str:
        if role == "coder":
            steps["coder"] += 1
            return tool("read_file", path="src/calc.py")
        return happy_policy(role, prompt, system)

    result = make(env, verbose_coder, max_rounds=1).run("fix add()")

    coder = get_role("coder")
    assert steps["coder"] <= coder.max_steps + 2, "the role's step budget applies"
    # repeating the same call trips the loop guard, which is itself a bound
    coder_run = next(run for run in result.role_runs if run.role == "coder")
    assert coder_run.status in ("max_steps", "loop")
    assert result.status in ("error", "max_rounds", "stalled")


# --- hard constraint: no bypassing the Executor ----------------------------


def test_a_role_cannot_use_a_tool_outside_its_allowlist(env) -> None:
    """Capability, not instruction: the Planner has no write tool registered."""
    _project, _store, context, sessions, builder, registry = env
    orchestrator = AgentOrchestrator(
        CallableModel(lambda prompt, system: tool("write_file", path="src/calc.py", content="hacked")),
        sessions,
        context,
        builder=builder,
        registry=registry,
    )

    planner_executor = orchestrator.executor_for(get_role("planner"))

    assert "write_file" not in planner_executor.registry.names()
    assert "apply_patch" not in planner_executor.registry.names()


def test_a_planner_that_asks_to_write_changes_nothing(env) -> None:
    project = env[0]

    def writes_anyway(role: str, prompt: str, system: str) -> str:
        if role == "planner":
            return tool("write_file", path="src/calc.py", content="hacked")
        return happy_policy(role, prompt, system)

    result = make(env, writes_anyway).run("fix add()")

    # The file is untouched: the planner has no write tool to call.
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") == BROKEN
    planner_runs = [run for run in result.role_runs if run.role == "planner"]
    assert planner_runs, "the planner still ran"
    assert planner_runs[0].tools_used == [], "no tool executed for the planner"
    # the role cannot proceed, and it says why: the tool it asked for is not
    # among the ones it has
    assert planner_runs[0].status in ("error", "loop", "max_steps")
    notices = [
        event
        for event in result.events
        if event.type == "parse_failed" or (event.type == "tool_result" and not event.ok)
    ]
    assert notices, "the attempt to use a missing tool was reported, not silently dropped"
    assert any("unknown_tool" in str(event.data) or "no tool call" in event.message.lower()
               or "unknown" in event.message.lower()
               for event in notices) or planner_runs[0].status == "error"


def test_the_reviewer_cannot_patch_even_when_asked(env) -> None:
    project = env[0]

    def reviewer_writes(role: str, prompt: str, system: str) -> str:
        if role == "reviewer":
            return tool(
                "apply_patch",
                path="src/calc.py",
                hunks=[{"old": "return a + b", "new": "return a * b"}],
            )
        return happy_policy(role, prompt, system)

    result = make(env, reviewer_writes, max_rounds=1).run("fix add()")

    # the coder's patch stands; the reviewer's attempted rewrite never ran
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") != (
        "def add(a, b):" + chr(10) + "    return a * b" + chr(10)
    )
    reviewer_run = next(run for run in result.role_runs if run.role == "reviewer")
    assert reviewer_run.tools_used == []


def test_role_restrictions_come_from_the_registry(env) -> None:
    _project, _store, context, sessions, builder, registry = env
    orchestrator = AgentOrchestrator(
        CallableModel(happy_policy), sessions, context, builder=builder, registry=registry
    )

    for name in ("planner", "coder", "reviewer", "memory_curator", "state_keeper", "safety_guard"):
        role = get_role(name)
        scoped = orchestrator.executor_for(role).registry
        assert scoped.names() == sorted(role.allowed_tools)


def test_an_unknown_tool_in_a_allowlist_is_refused(env) -> None:
    """A typo in a role definition must fail loudly, not silently widen."""
    _project, _store, context, sessions, builder, registry = env
    orchestrator = AgentOrchestrator(
        CallableModel(happy_policy), sessions, context, builder=builder, registry=registry
    )
    from app.tools.errors import ToolNotFoundError

    with pytest.raises(ToolNotFoundError):
        registry.subset(["read_file", "delete_everything"])


# --- hard constraint: no direct shared-state writes ------------------------


def test_only_the_tools_change_shared_state(env) -> None:
    """Project State and Memory move through their tools, never directly."""
    project, store, _context, sessions, _builder, _registry = env
    before_state = store.load_project_state().model_dump(mode="json")

    def never_updates(role: str, prompt: str, system: str) -> str:
        if role == "state_keeper":
            return "nothing to record"
        if role == "memory_curator":
            return "nothing to remember"
        return happy_policy(role, prompt, system)

    make(env, never_updates).run("fix add()")

    after = store.load_project_state().model_dump(mode="json")
    assert after["current_task"] == before_state["current_task"], (
        "a role saying it did nothing must leave the state alone"
    )
    assert sessions.memory.count() == 0


def test_the_memory_curator_proposes_through_the_review_pipeline(env) -> None:
    _project, _store, _context, sessions, _builder, _registry = env

    def curator_proposes(role: str, prompt: str, system: str) -> str:
        if role == "memory_curator":
            return tool("memory_propose", key="gate", value="pytest is the gate")
        return happy_policy(role, prompt, system)

    result = make(env, curator_proposes).run("fix add()")

    assert "memory_propose" in result.tools_by_role()["memory_curator"]
    assert sessions.memory.get("gate") is not None


def test_a_secret_proposal_is_rejected_by_the_pipeline(env) -> None:
    _project, _store, _context, sessions, _builder, _registry = env

    def curator_leaks(role: str, prompt: str, system: str) -> str:
        if role == "memory_curator":
            return tool("memory_propose", key="leak", value="password: hunter2hunter2")
        return happy_policy(role, prompt, system)

    make(env, curator_leaks).run("fix add()")

    assert sessions.memory.get("leak") is None, "the review pipeline still applies"


# --- the safety guard ------------------------------------------------------


def test_a_blocked_plan_stops_before_the_coder_runs(env) -> None:
    project = env[0]
    stated: list[str] = []

    def guard_blocks(role: str, prompt: str, system: str) -> str:
        if role == "safety_guard":
            return "VERDICT: BLOCKED" + chr(10) + "ISSUE: the plan deletes the repository"
        if role == "coder":
            stated.append("coder ran")
        return happy_policy(role, prompt, system)

    result = make(env, guard_blocks).run("fix add()")

    assert result.status == "blocked"
    assert "deletes the repository" in result.reason
    assert stated == [], "the coder must not run after a block"
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8") == BROKEN


def test_a_guard_without_a_verdict_does_not_block(env) -> None:
    """unknown is not blocked: only a stated risk stops the work."""

    def guard_mumbles(role: str, prompt: str, system: str) -> str:
        if role == "safety_guard":
            return "seems fine"
        return happy_policy(role, prompt, system)

    result = make(env, guard_mumbles).run("fix add()")

    assert result.status == "completed"


def test_the_safety_layer_still_applies_inside_a_role(env) -> None:
    """The roles run through the Executor, so the M4 policy is unchanged."""
    project = env[0]
    outside = project.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    def coder_reaches_out(role: str, prompt: str, system: str) -> str:
        if role == "coder":
            return tool("read_file", path=str(outside))
        return happy_policy(role, prompt, system)

    result = make(env, coder_reaches_out, max_rounds=1).run("fix add()")

    assert result.tool_failures >= 1
    assert not any("secret" in event.message for event in result.events)


# --- events ----------------------------------------------------------------


def test_events_are_tagged_with_the_role(env) -> None:
    seen: list[tuple[str, str]] = []

    orchestrator = make(env, happy_policy)
    orchestrator.on_event = lambda event: seen.append(
        (str(event.data.get("role", "")), event.type)
    )

    orchestrator.run("fix add()")

    roles = {role for role, _type in seen if role}
    assert {"planner", "coder", "reviewer"} <= roles


def test_the_result_renders_a_summary(env) -> None:
    result = make(env, happy_policy).run("fix add()")

    assert result.role_summary()["coder"] == 1
    assert result.tools_by_role()["coder"]


def test_every_role_writes_to_the_tool_audit_log(env) -> None:
    """Multi-agent tool calls are audited exactly like single-agent ones."""
    project, _store, context, sessions, builder, registry = env
    log_path = project / "runs" / "tool-calls.jsonl"
    orchestrator = AgentOrchestrator(
        CallableModel(lambda prompt, system: happy_policy(which_role(system or ""), prompt, system or "")),
        sessions,
        context,
        builder=builder,
        limits=OrchestrationLimits(max_rounds=2, timeout_ms=60_000),
        registry=registry,
        confirm=lambda request: "once",
        log_path=log_path,
    )

    orchestrator.run("fix add()")

    assert log_path.exists(), "the roles' tool calls must be logged"
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    names = {record["name"] for record in records}
    assert {"apply_patch", "run_shell"} <= names


def test_a_coder_that_fails_ends_the_collaboration(env) -> None:
    from app.agents import ModelClientError

    def coder_dies(role: str, prompt: str, system: str) -> str:
        if role == "coder":
            raise ModelClientError("the page died")
        return happy_policy(role, prompt, system)

    result = make(env, coder_dies).run("fix add()")

    assert result.status == "error"
