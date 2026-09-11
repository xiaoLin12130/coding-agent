"""The shell timeout must actually return.

A real run froze for minutes on a generated test command because that test
started an HTTP server: subprocess.run(timeout=...) killed only the shell on
Windows, the grandchild kept the stdout pipe open, and the call never came back.
The whole agent run was stuck behind it.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from app.config import AppPaths
from app.storage import StateStore
from app.tools import Executor, ToolCall, ToolContext, build_default_registry
from app.tools.builtin import kill_process_tree

SLEEPER = "import time" + chr(10) + "time.sleep(60)" + chr(10)
SPAWNER = (
    "import subprocess"
    + chr(10)
    + "import sys"
    + chr(10)
    + "import time"
    + chr(10)
    + chr(10)
    + 'subprocess.Popen([sys.executable, "sleeper.py"])'
    + chr(10)
    + 'print("child started", flush=True)'
    + chr(10)
    + "time.sleep(60)"
    + chr(10)
)


@pytest.fixture()
def executor(tmp_path: Path):
    paths = AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )
    context = ToolContext(working_dir=tmp_path, store=StateStore(paths))
    return context, Executor(
        build_default_registry(context), context, log_path=tmp_path / "runs" / "log.jsonl"
    )


def test_a_command_that_spawns_a_child_still_times_out(executor, tmp_path: Path) -> None:
    _context, runner = executor
    (tmp_path / "sleeper.py").write_text(SLEEPER, encoding="utf-8")
    (tmp_path / "spawner.py").write_text(SPAWNER, encoding="utf-8")

    started = time.monotonic()
    result = runner.execute(
        ToolCall(
            id="call-1",
            name="run_shell",
            arguments={"command": "python spawner.py", "timeout_ms": 3000},
        ),
        confirmed=True,
    )
    elapsed = time.monotonic() - started

    assert result.ok is False
    assert result.error is not None and result.error.code == "execution_failed"
    assert "timed out" in (result.error.message or "")
    assert elapsed < 30, "the timeout did not return promptly (%.1fs)" % elapsed


def test_a_normal_command_is_unaffected(executor) -> None:
    _context, runner = executor
    result = runner.execute(
        ToolCall(id="call-1", name="run_shell", arguments={"command": "python --version"}),
        confirmed=True,
    )
    assert result.ok is True
    assert "Python" in result.output


def test_killing_an_already_finished_process_is_safe(executor) -> None:
    _context, _runner = executor
    finished = subprocess.Popen(["python", "-c", "pass"])
    finished.wait(timeout=30)
    kill_process_tree(finished)
