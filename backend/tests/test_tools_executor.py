"""Executor tests: schema validation, confirmation seam, logging, idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppPaths
from app.context.memory import MemoryStore
from app.storage import StateStore
from app.tools import (
    Executor,
    ToolCall,
    ToolContext,
    default_registry,
    idempotency_key,
)


@pytest.fixture()
def workspace(tmp_path: Path):
    paths = AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(
        working_dir=tmp_path,
        store=store,
        memory=MemoryStore(store),
        user_resolver=lambda question: "approved by the test",
    )
    return tmp_path, context


@pytest.fixture()
def executor(workspace):
    cwd, context = workspace
    return Executor(
        default_registry(),
        context,
        log_path=cwd / "runs" / "tool-calls.jsonl",
    )


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(id="call-" + name, name=name, arguments=arguments)


# --- validation -----------------------------------------------------------


def test_valid_call_succeeds(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "a.txt").write_text("hello", encoding="utf-8")

    result = executor.execute(call("read_file", path="a.txt"))

    assert result.ok is True
    assert "hello" in result.output
    assert result.error is None
    assert result.duration_ms >= 0


def test_unknown_tool_is_reported_not_raised(executor) -> None:
    result = executor.execute(call("does_not_exist"))

    assert result.ok is False
    assert result.error.code == "unknown_tool"
    assert result.error.retryable is True


def test_schema_violation_reports_every_field(executor) -> None:
    result = executor.execute(call("read_file", path=123))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"
    assert result.error.details["errors"][0]["location"] == ["path"]


def test_missing_required_argument_is_reported(executor) -> None:
    result = executor.execute(call("write_file", path="x.txt"))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"
    assert "content" in json.dumps(result.error.details)


def test_extra_arguments_are_rejected(executor) -> None:
    result = executor.execute(call("read_file", path="a.txt", surprise=1))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"


def test_bounded_numeric_argument_is_enforced(executor) -> None:
    result = executor.execute(call("search", pattern="x", max_results=10_000))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"


# --- error handling -------------------------------------------------------


def test_tool_execution_error_becomes_a_result(executor) -> None:
    result = executor.execute(call("read_file", path="missing.txt"))

    assert result.ok is False
    assert result.error.code == "execution_failed"
    assert "no such file" in result.error.message


def test_unexpected_exception_is_contained(workspace) -> None:
    cwd, context = workspace
    registry = default_registry()

    @registry.tool("explode", "always fails", type("Args", (__import__("pydantic").BaseModel,), {}))
    def explode(args, ctx=None):  # pragma: no cover - trivial
        raise ValueError("boom")

    executor = Executor(registry, context)
    result = executor.execute(call("explode"))

    assert result.ok is False
    assert result.error.code == "internal_error"
    assert "ValueError" in result.error.message
    assert result.error.retryable is False


def test_one_failure_does_not_stop_the_next_call(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "ok.txt").write_text("fine", encoding="utf-8")

    results = executor.execute_all(
        [call("read_file", path="nope.txt"), call("read_file", path="ok.txt")]
    )

    assert [r.ok for r in results] == [False, True]


# --- the confirmation seam (M4 fills it) ---------------------------------


def test_high_risk_tool_refuses_without_confirmation(executor) -> None:
    result = executor.execute(call("run_shell", command="echo hi"))

    assert result.ok is False
    assert result.error.code == "confirmation_required"
    assert result.risk == "high"


def test_explicit_confirmation_allows_the_call(executor) -> None:
    result = executor.execute(call("run_shell", command="echo hi"), confirmed=True)

    assert result.ok is True
    assert "hi" in result.output


def test_approval_hook_can_grant_the_call(workspace) -> None:
    cwd, context = workspace
    seen: list[str] = []

    def approve(call_: ToolCall) -> bool:
        seen.append(call_.name)
        return True

    executor = Executor(default_registry(), context, approval=approve)
    result = executor.execute(call("run_shell", command="echo hooked"))

    assert seen == ["run_shell"]
    assert result.ok is True


def test_approval_hook_can_deny_the_call(workspace) -> None:
    cwd, context = workspace
    executor = Executor(default_registry(), context, approval=lambda call_: False)

    result = executor.execute(call("run_shell", command="echo nope"))

    assert result.ok is False
    assert result.error.code == "confirmation_required"


def test_low_risk_tools_never_ask_for_confirmation(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "a.txt").write_text("x", encoding="utf-8")

    result = executor.execute(call("read_file", path="a.txt"))

    assert result.ok is True


def test_every_tool_declares_a_risk_level(executor) -> None:
    for spec in executor.registry.specs():
        assert spec.risk in ("low", "medium", "high")
        assert spec.name
        assert spec.description
        assert spec.parameters.get("type") == "object"


def test_only_run_shell_requires_confirmation(executor) -> None:
    requiring = [
        spec.name for spec in executor.registry.specs() if spec.requires_confirmation
    ]
    assert requiring == ["run_shell"]


# --- idempotency ----------------------------------------------------------


def test_identical_idempotent_call_is_replayed(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "a.txt").write_text("x", encoding="utf-8")

    first = executor.execute(call("read_file", path="a.txt"))
    second = executor.execute(call("read_file", path="a.txt"))

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.output == first.output


def test_different_arguments_are_not_replayed(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "a.txt").write_text("x", encoding="utf-8")
    (cwd / "b.txt").write_text("y", encoding="utf-8")

    executor.execute(call("read_file", path="a.txt"))
    second = executor.execute(call("read_file", path="b.txt"))

    assert second.idempotent_replay is False


def test_failures_are_not_cached(executor) -> None:
    first = executor.execute(call("read_file", path="missing.txt"))
    second = executor.execute(call("read_file", path="missing.txt"))

    assert first.ok is False and second.ok is False
    assert second.idempotent_replay is False


def test_non_idempotent_tool_is_never_replayed(executor, workspace) -> None:
    cwd, _ = workspace
    (cwd / "p.txt").write_text("old", encoding="utf-8")
    patch = call("apply_patch", path="p.txt", hunks=[{"old": "old", "new": "new"}])

    first = executor.execute(patch)
    second = executor.execute(patch)

    assert first.ok is True
    assert second.idempotent_replay is False
    assert second.ok is False, "the second patch cannot match the replaced text"


def test_a_write_invalidates_cached_reads(workspace) -> None:
    """A replayed read must never show content from before a write."""
    cwd, context = workspace
    target = cwd / "a.txt"
    target.write_text("before", encoding="utf-8")
    executor = Executor(default_registry(), context)

    first = executor.execute(call("read_file", path="a.txt"))
    executor.execute(call("write_file", path="a.txt", content="after"))
    second = executor.execute(call("read_file", path="a.txt"))

    assert "before" in first.output
    assert "after" in second.output, "the cached read was served after a write"
    assert second.idempotent_replay is False


def test_a_patch_invalidates_cached_reads(workspace) -> None:
    cwd, context = workspace
    target = cwd / "a.txt"
    target.write_text("old text", encoding="utf-8")
    executor = Executor(default_registry(), context)

    executor.execute(call("read_file", path="a.txt"))
    executor.execute(
        call("apply_patch", path="a.txt", hunks=[{"old": "old", "new": "new"}])
    )
    after = executor.execute(call("read_file", path="a.txt"))

    assert "new text" in after.output


def test_reads_are_still_replayed_without_an_intervening_write(workspace) -> None:
    cwd, context = workspace
    (cwd / "a.txt").write_text("stable", encoding="utf-8")
    executor = Executor(default_registry(), context)

    executor.execute(call("read_file", path="a.txt"))
    second = executor.execute(call("read_file", path="a.txt"))

    assert second.idempotent_replay is True, "the cache still works when nothing changed"


def test_replay_can_be_disabled(workspace) -> None:
    cwd, context = workspace
    (cwd / "a.txt").write_text("x", encoding="utf-8")
    executor = Executor(default_registry(), context, replay_cache=False)

    executor.execute(call("read_file", path="a.txt"))
    second = executor.execute(call("read_file", path="a.txt"))

    assert second.idempotent_replay is False


def test_idempotency_key_is_stable_and_argument_order_independent() -> None:
    one = ToolCall(id="a", name="write_file", arguments={"path": "p", "content": "c"})
    two = ToolCall(id="b", name="write_file", arguments={"content": "c", "path": "p"})
    other = ToolCall(id="c", name="write_file", arguments={"path": "p", "content": "d"})

    assert idempotency_key(one) == idempotency_key(two)
    assert idempotency_key(one) != idempotency_key(other)


# --- logging --------------------------------------------------------------


def test_every_call_is_logged_in_memory(executor) -> None:
    executor.execute(call("list_dir", path="."))
    executor.execute(call("nope"))

    assert [entry.name for entry in executor.log] == ["list_dir", "nope"]
    assert executor.log[0].ok is True
    assert executor.log[1].ok is False
    assert executor.log[1].error_code == "unknown_tool"


def test_log_is_written_as_jsonl(workspace) -> None:
    cwd, context = workspace
    log_path = cwd / "runs" / "tool-calls.jsonl"
    executor = Executor(default_registry(), context, log_path=log_path)

    executor.execute(call("list_dir", path="."))

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["name"] == "list_dir"
    assert record["ok"] is True
    assert "at" in record


def test_log_records_confirmation_and_replay(workspace) -> None:
    cwd, context = workspace
    executor = Executor(default_registry(), context)

    executor.execute(call("run_shell", command="echo hi"), confirmed=True)
    executor.execute(call("list_dir", path="."))
    executor.execute(call("list_dir", path="."))

    assert executor.log[0].confirmed is True
    assert executor.log[2].idempotent_replay is True


def test_arguments_preview_is_bounded(executor) -> None:
    executor.execute(call("write_file", path="big.txt", content="x" * 5000))

    assert len(executor.log[0].arguments_preview) <= 200


def test_a_broken_log_path_does_not_break_execution(workspace, tmp_path) -> None:
    cwd, context = workspace
    blocked = tmp_path / "a-file" / "nested" / "log.jsonl"
    (tmp_path / "a-file").write_text("not a directory", encoding="utf-8")
    executor = Executor(default_registry(), context, log_path=blocked)

    result = executor.execute(call("list_dir", path="."))

    assert result.ok is True, "logging must never break an execution"
