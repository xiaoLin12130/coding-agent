"""Built-in tool tests: the nine M3 tools, including their failure paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppPaths
from app.context.memory import MemoryStore
from app.models import TodoItem
from app.storage import StateStore
from app.tools import Executor, ToolCall, ToolContext, build_default_registry


@pytest.fixture()
def env(tmp_path: Path):
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
        user_resolver=lambda question: "yes",
    )
    return tmp_path, store, Executor(build_default_registry(context), context)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(id="c-" + name, name=name, arguments=arguments)


# --- list_dir -------------------------------------------------------------


def test_list_dir_lists_entries(env) -> None:
    cwd, _store, executor = env
    (cwd / "src").mkdir()
    (cwd / "src" / "a.py").write_text("x", encoding="utf-8")
    (cwd / "README.md").write_text("y", encoding="utf-8")

    result = executor.execute(call("list_dir", path="."))

    assert result.ok is True
    assert "src/" in result.output
    assert "README.md" in result.output
    assert result.data["count"] >= 2


def test_list_dir_hides_dotfiles_by_default(env) -> None:
    cwd, _store, executor = env
    (cwd / ".hidden").write_text("x", encoding="utf-8")
    (cwd / "shown.txt").write_text("y", encoding="utf-8")

    default = executor.execute(call("list_dir", path="."))
    explicit = executor.execute(call("list_dir", path=".", include_hidden=True))

    assert ".hidden" not in default.output
    assert ".hidden" in explicit.output


def test_list_dir_skips_heavy_directories(env) -> None:
    cwd, _store, executor = env
    (cwd / "node_modules").mkdir()
    (cwd / "node_modules" / "x.js").write_text("x", encoding="utf-8")

    result = executor.execute(call("list_dir", path=".", depth=3))

    assert "skipped" in result.output


def test_list_dir_rejects_a_file(env) -> None:
    cwd, _store, executor = env
    (cwd / "f.txt").write_text("x", encoding="utf-8")

    result = executor.execute(call("list_dir", path="f.txt"))

    assert result.ok is False
    assert "not a directory" in result.error.message


def test_list_dir_rejects_a_missing_path(env) -> None:
    _cwd, _store, executor = env
    result = executor.execute(call("list_dir", path="nowhere"))
    assert result.ok is False
    assert "no such directory" in result.error.message


# --- read_file ------------------------------------------------------------


def test_read_file_numbers_lines(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = executor.execute(call("read_file", path="a.txt"))

    assert result.ok is True
    assert "1| one" in result.output
    assert "3| three" in result.output
    assert result.data["total_lines"] == 3


def test_read_file_line_range(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = executor.execute(call("read_file", path="a.txt", start_line=2, end_line=2))

    assert "2| two" in result.output
    assert "one" not in result.output


def test_read_file_rejects_a_directory(env) -> None:
    cwd, _store, executor = env
    (cwd / "d").mkdir()

    result = executor.execute(call("read_file", path="d"))

    assert result.ok is False
    assert "not a file" in result.error.message


def test_read_file_rejects_binary_content(env) -> None:
    cwd, _store, executor = env
    (cwd / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")

    result = executor.execute(call("read_file", path="bin.dat"))

    assert result.ok is False
    assert "UTF-8" in result.error.message


def test_read_file_resolves_relative_to_the_working_dir(env) -> None:
    cwd, _store, executor = env
    (cwd / "nested").mkdir()
    (cwd / "nested" / "deep.txt").write_text("deep", encoding="utf-8")

    result = executor.execute(call("read_file", path="nested/deep.txt"))

    assert result.ok is True
    assert str(cwd) in result.output


# --- write_file -----------------------------------------------------------


def test_write_file_creates_and_reports(env) -> None:
    cwd, _store, executor = env

    result = executor.execute(call("write_file", path="new/thing.txt", content="hi"))

    assert result.ok is True
    assert result.data["created"] is True
    assert (cwd / "new" / "thing.txt").read_text(encoding="utf-8") == "hi"


def test_write_file_updates_an_existing_file(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("old content", encoding="utf-8")

    result = executor.execute(call("write_file", path="a.txt", content="new"))

    assert result.data["created"] is False
    assert result.data["replaced_chars"] == len("old content")
    assert (cwd / "a.txt").read_text(encoding="utf-8") == "new"


def test_write_file_can_skip_parent_creation(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("write_file", path="missing/x.txt", content="y", create_parents=False)
    )

    assert result.ok is False


# --- apply_patch ----------------------------------------------------------


def test_apply_patch_replaces_one_fragment(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    result = executor.execute(
        call("apply_patch", path="a.py", hunks=[{"old": "return 1", "new": "return 2"}])
    )

    assert result.ok is True
    assert "return 2" in (cwd / "a.py").read_text(encoding="utf-8")


def test_apply_patch_applies_several_hunks_in_order(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("alpha beta gamma", encoding="utf-8")

    result = executor.execute(
        call(
            "apply_patch",
            path="a.txt",
            hunks=[
                {"old": "alpha", "new": "ALPHA"},
                {"old": "gamma", "new": "GAMMA"},
            ],
        )
    )

    assert result.ok is True
    assert (cwd / "a.txt").read_text(encoding="utf-8") == "ALPHA beta GAMMA"


def test_apply_patch_refuses_an_ambiguous_anchor(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("dup dup", encoding="utf-8")

    result = executor.execute(
        call("apply_patch", path="a.txt", hunks=[{"old": "dup", "new": "x"}])
    )

    assert result.ok is False
    assert "matches 2 places" in result.error.message
    assert (cwd / "a.txt").read_text(encoding="utf-8") == "dup dup", "nothing may change"


def test_apply_patch_failure_leaves_the_file_untouched(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("keep me", encoding="utf-8")

    result = executor.execute(
        call(
            "apply_patch",
            path="a.txt",
            hunks=[{"old": "keep me", "new": "changed"}, {"old": "absent", "new": "x"}],
        )
    )

    assert result.ok is False
    assert (cwd / "a.txt").read_text(encoding="utf-8") == "keep me"


def test_apply_patch_requires_a_hunk(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("x", encoding="utf-8")

    result = executor.execute(call("apply_patch", path="a.txt", hunks=[]))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"


def test_apply_patch_reports_a_missing_file(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("apply_patch", path="ghost.txt", hunks=[{"old": "a", "new": "b"}])
    )

    assert result.ok is False
    assert "no such file" in result.error.message


# --- search ---------------------------------------------------------------


def test_search_finds_matches_with_line_numbers(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.py").write_text("import os\n\ndef target():\n    pass\n", encoding="utf-8")

    result = executor.execute(call("search", pattern="def target", include="*.py"))

    assert result.ok is True
    assert "a.py:3:" in result.output
    assert result.data["matches"] == 1


def test_search_respects_the_include_filter(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.py").write_text("needle", encoding="utf-8")
    (cwd / "b.md").write_text("needle", encoding="utf-8")

    result = executor.execute(call("search", pattern="needle", include="*.md"))

    assert result.data["matches"] == 1
    assert "b.md" in result.output


def test_search_accepts_a_file_target(env) -> None:
    cwd, _store, executor = env
    (cwd / "only.txt").write_text("find me", encoding="utf-8")

    result = executor.execute(call("search", pattern="find", path="only.txt"))

    assert result.data["matches"] == 1


def test_search_reports_an_invalid_regex(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("search", pattern="([unclosed"))

    assert result.ok is False
    assert result.error.code == "invalid_arguments"


def test_search_returns_no_matches_without_failing(env) -> None:
    cwd, _store, executor = env
    (cwd / "a.txt").write_text("nothing here", encoding="utf-8")

    result = executor.execute(call("search", pattern="absent"))

    assert result.ok is True
    assert result.data["matches"] == 0


def test_search_skips_ignored_directories(env) -> None:
    cwd, _store, executor = env
    (cwd / "node_modules").mkdir()
    (cwd / "node_modules" / "x.js").write_text("needle", encoding="utf-8")
    (cwd / "keep.txt").write_text("needle", encoding="utf-8")

    result = executor.execute(call("search", pattern="needle"))

    assert result.data["matches"] == 1


# --- run_shell ------------------------------------------------------------


def test_run_shell_captures_stdout(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("run_shell", command="echo hello"), confirmed=True)

    assert result.ok is True
    assert "hello" in result.output
    assert result.data["exit_code"] == 0


def test_run_shell_reports_a_nonzero_exit(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("run_shell", command="exit 3"), confirmed=True)

    assert result.ok is True, "a failing command is still a completed call"
    assert result.data["exit_code"] == 3


def test_run_shell_reports_stderr(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("run_shell", command="echo oops 1>&2"), confirmed=True
    )

    assert "stderr" in result.output
    assert "oops" in result.output


def test_run_shell_times_out(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("run_shell", command="sleep 5", timeout_ms=1500), confirmed=True
    )

    assert result.ok is False
    assert "timed out" in result.error.message


def test_run_shell_rejects_a_missing_working_directory(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("run_shell", command="echo x", cwd="no/such/dir"), confirmed=True
    )

    assert result.ok is False
    assert "working directory" in result.error.message


def test_run_shell_output_is_bounded(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("run_shell", command="python -c \"print('x' * 60000)\""), confirmed=True
    )

    assert result.ok is True
    assert "truncated" in result.output


# --- memory_propose -------------------------------------------------------


def test_memory_propose_stores_through_the_review_pipeline(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("memory_propose", key="stack", value="fastapi"))

    assert result.ok is True
    assert result.data["decision"] == "accepted"


def test_memory_propose_rejects_a_secret(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(
        call("memory_propose", key="leak", value="password: hunter2hunter2")
    )

    assert result.ok is False
    assert "not stored" in result.error.message


def test_memory_propose_rejects_a_duplicate(env) -> None:
    _cwd, _store, executor = env
    executor.execute(call("memory_propose", key="a", value="same"))

    result = executor.execute(call("memory_propose", key="b", value="same"))

    assert result.ok is False
    assert "duplicate" in result.error.message


# --- update_project_state -------------------------------------------------


def test_update_project_state_changes_only_given_fields(env) -> None:
    _cwd, store, executor = env
    from app.models import ProjectState

    store.save_project_state(
        ProjectState(current_milestone="M2", current_task="old task", goal="keep me")
    )

    result = executor.execute(
        call("update_project_state", current_task="new task", git_branch="main")
    )

    assert result.ok is True
    saved = store.load_project_state()
    assert saved.current_milestone == "M2", "untouched fields must survive"
    assert saved.goal == "keep me"
    assert saved.current_task == "new task"
    assert saved.git_branch == "main"
    assert set(result.data["changed"]) == {"current_task", "git_branch"}


def test_update_project_state_appends_lists_without_duplicates(env) -> None:
    _cwd, store, executor = env

    executor.execute(call("update_project_state", add_files_changed=["a.py"]))
    executor.execute(call("update_project_state", add_files_changed=["a.py", "b.py"]))

    saved = store.load_project_state()
    assert saved.files_changed == ["a.py", "b.py"]


def test_update_project_state_records_tests_failures_and_decisions(env) -> None:
    _cwd, store, executor = env

    executor.execute(
        call(
            "update_project_state",
            add_test_result="pytest 150 passed",
            add_failures=["flaky test"],
            add_decisions=["use characters as the budget unit"],
        )
    )

    saved = store.load_project_state()
    assert saved.tests == ["pytest 150 passed"]
    assert saved.failures == ["flaky test"]
    assert saved.decisions == ["use characters as the budget unit"]


def test_update_project_state_replaces_todos(env) -> None:
    _cwd, store, executor = env

    executor.execute(
        call(
            "update_project_state",
            set_todos=[{"content": "write the parser", "status": "completed"}],
        )
    )

    saved = store.load_project_state()
    assert saved.todos == [TodoItem(content="write the parser", status="completed")]


def test_update_project_state_reports_no_change(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("update_project_state"))

    assert result.ok is True
    assert result.data["changed"] == []
    assert "unchanged" in result.output


# --- ask_user -------------------------------------------------------------


def test_ask_user_returns_the_answer(env) -> None:
    _cwd, _store, executor = env

    result = executor.execute(call("ask_user", question="proceed?"))

    assert result.ok is True
    assert result.data["answer"] == "yes"


def test_ask_user_without_a_channel_fails_cleanly(env) -> None:
    cwd, store, _executor = env
    context = ToolContext(working_dir=cwd, store=store, memory=MemoryStore(store))
    executor = Executor(build_default_registry(context), context)

    result = executor.execute(call("ask_user", question="anyone?"))

    assert result.ok is False
    assert "no user channel" in result.error.message


# --- catalogue ------------------------------------------------------------


def test_all_nine_required_tools_exist(env) -> None:
    _cwd, _store, executor = env

    assert set(executor.registry.names()) == {
        "list_dir",
        "read_file",
        "write_file",
        "apply_patch",
        "search",
        "run_shell",
        "memory_propose",
        "update_project_state",
        "ask_user",
    }


def test_schemas_are_publishable(env) -> None:
    _cwd, _store, executor = env

    schemas = executor.registry.schemas()

    assert len(schemas) == 9
    for schema in schemas:
        assert schema["name"]
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert "properties" in schema["parameters"]


def test_duplicate_registration_is_refused(env) -> None:
    _cwd, _store, executor = env
    registry = executor.registry
    existing = registry.get("read_file")

    with pytest.raises(ValueError):
        registry.register(existing)
