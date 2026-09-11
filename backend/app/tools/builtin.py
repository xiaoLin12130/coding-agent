"""The nine M3 tools.

Risk levels follow docs/safety.md (read -> LOW, modify project files ->
MEDIUM, delete/system-level -> HIGH). M3 declares the risk; M4 is what turns
that declaration into a policy with path limits, sensitive-file checks and the
confirmation UI.

Every handler returns a ToolOutcome: the model-facing text plus optional
artifacts and structured data. Output is DATA, never an instruction.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from ..context.memory import MemoryStore
from ..context.models import MemoryProposal
from ..models import ProjectState, TodoItem
from ..storage import StateStore
from .errors import ToolExecutionError, ToolValidationError
from .registry import ToolRegistry

# Directories never worth walking for a code search.
SKIPPED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "runs",
    ".browser-profile",
}

MAX_READ_BYTES = 512_000
MAX_SEARCH_RESULTS = 200
MAX_LIST_ENTRIES = 500
MAX_OUTPUT_CHARS = 40_000
DEFAULT_SHELL_TIMEOUT_MS = 60_000
MAX_SHELL_TIMEOUT_MS = 600_000


@dataclass
class ToolContext:
    """Everything a tool needs from the surrounding system."""

    working_dir: Path
    store: StateStore
    memory: MemoryStore | None = None
    user_resolver: Callable[[str], str] | None = None
    artifacts: list[str] = field(default_factory=list)

    def resolve(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.working_dir / candidate
        return candidate


@dataclass
class ToolOutcome:
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)


def kill_process_tree(process: "subprocess.Popen") -> None:
    """Kill a shell command AND everything it started.

    A test runner that spawns a server, a command that backgrounds a watcher:
    killing only the shell leaves them running and holding the pipes, so the
    caller never sees an answer. On Windows taskkill /T walks the tree; on POSIX
    the process group does.
    """
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
            )
        else:  # pragma: no cover - the suite runs on Windows
            import signal

            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


def clip_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 60] + "\n...[output truncated at " + str(limit) + " chars]..."


# ---------------------------------------------------------------------------
# argument models
# ---------------------------------------------------------------------------


class ToolArgs(BaseModel):
    """Base for every tool's arguments.

    Unknown parameters are REJECTED: a model that invents an argument has
    misunderstood the tool, and silently dropping it would hide the mistake.
    """

    model_config = ConfigDict(extra="forbid")


class ListDirArgs(ToolArgs):
    path: str = Field(default=".", description="directory to list")
    depth: int = Field(default=1, ge=1, le=4, description="how deep to recurse")
    include_hidden: bool = Field(default=False)


class ReadFileArgs(ToolArgs):
    path: str = Field(description="file to read")
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class WriteFileArgs(ToolArgs):
    path: str = Field(description="file to write")
    content: str = Field(description="full new content")
    create_parents: bool = Field(default=True)


class PatchHunk(ToolArgs):
    old: str = Field(description="exact text to replace")
    new: str = Field(description="replacement text")


class ApplyPatchArgs(ToolArgs):
    path: str = Field(description="file to patch")
    hunks: list[PatchHunk] = Field(default_factory=list)
    create_if_missing: bool = Field(default=False)


class SearchArgs(ToolArgs):
    pattern: str = Field(description="regular expression to search for")
    path: str = Field(default=".")
    include: str | None = Field(default=None, description="glob filter, e.g. *.py")
    max_results: int = Field(default=50, ge=1, le=MAX_SEARCH_RESULTS)
    ignore_case: bool = Field(default=False)


class RunShellArgs(ToolArgs):
    command: str = Field(description="shell command to run")
    cwd: str | None = Field(default=None)
    timeout_ms: int = Field(default=DEFAULT_SHELL_TIMEOUT_MS, ge=1, le=MAX_SHELL_TIMEOUT_MS)


class MemoryProposeArgs(ToolArgs):
    key: str
    value: str
    namespace: str = "user"
    reason: str = ""


class UpdateProjectStateArgs(ToolArgs):
    """A partial update: only the provided fields change."""

    current_milestone: str | None = None
    current_task: str | None = None
    goal: str | None = None
    checkpoint: str | None = None
    git_branch: str | None = None
    add_files_changed: list[str] = Field(default_factory=list)
    add_decisions: list[str] = Field(default_factory=list)
    add_failures: list[str] = Field(default_factory=list)
    add_test_result: str | None = None
    set_todos: list[TodoItem] | None = None


class AskUserArgs(ToolArgs):
    question: str
    options: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def build_default_registry(
    context: ToolContext | None = None,
    registry: ToolRegistry | None = None,
) -> ToolRegistry:
    """Create the registry with all nine tools.

    Handlers receive (args, context); the context may be supplied per call
    instead, which is how the Executor rebinds the working directory.
    """
    tools = registry or ToolRegistry()
    fallback = context

    def ctx_for(context_arg: ToolContext | None) -> ToolContext:
        active = context_arg or fallback
        if active is None:
            raise ToolExecutionError("no tool context was supplied")
        return active

    @tools.tool(
        "list_dir",
        "List files and directories under a path.",
        ListDirArgs,
        risk="low",
        idempotent=True,
    )
    def list_dir(args: ListDirArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        root = active.resolve(args.path)
        if not root.exists():
            raise ToolExecutionError("no such directory: " + str(root))
        if not root.is_dir():
            raise ToolExecutionError("not a directory: " + str(root))

        entries: list[str] = []
        truncated = False

        def walk(directory: Path, depth: int) -> None:
            nonlocal truncated
            try:
                children = sorted(
                    directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
                )
            except OSError as exc:
                entries.append("  [unreadable: " + str(exc) + "]")
                return
            for child in children:
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                    return
                name = child.name
                if not args.include_hidden and name.startswith("."):
                    continue
                if child.is_dir() and name in SKIPPED_DIRECTORIES:
                    entries.append("  " * (depth - 1) + name + "/ (skipped)")
                    continue
                suffix = "/" if child.is_dir() else ""
                entries.append("  " * (depth - 1) + name + suffix)
                if child.is_dir() and depth < args.depth:
                    walk(child, depth + 1)

        walk(root, 1)
        header = str(root) + " (" + str(len(entries)) + " entries)"
        if truncated:
            header += " [truncated]"
        return ToolOutcome(
            output=clip_output(header + "\n" + "\n".join(entries)),
            data={"path": str(root), "count": len(entries), "truncated": truncated},
        )

    @tools.tool(
        "read_file",
        "Read a text file, optionally a line range.",
        ReadFileArgs,
        risk="low",
        idempotent=True,
    )
    def read_file(args: ReadFileArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        path = active.resolve(args.path)
        if not path.exists():
            raise ToolExecutionError("no such file: " + str(path))
        if path.is_dir():
            raise ToolExecutionError("not a file: " + str(path))
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ToolExecutionError(
                "file is larger than " + str(MAX_READ_BYTES) + " bytes; read a line range"
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("file is not valid UTF-8 text: " + str(exc)) from exc

        lines = text.splitlines()
        total = len(lines)
        start = min(args.start_line, total) if total else 1
        end = total if args.end_line is None else min(args.end_line, total)
        selected = lines[start - 1 : end] if total else []
        numbered = "\n".join(
            str(start + offset) + "| " + line for offset, line in enumerate(selected)
        )
        header = str(path) + " (lines " + str(start) + "-" + str(end) + " of " + str(total) + ")"
        return ToolOutcome(
            output=clip_output(header + "\n" + numbered),
            data={"path": str(path), "total_lines": total, "start_line": start, "end_line": end},
        )

    @tools.tool(
        "write_file",
        "Write a file, replacing its content entirely.",
        WriteFileArgs,
        risk="medium",
        idempotent=True,
    )
    def write_file(args: WriteFileArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        path = active.resolve(args.path)
        existed = path.exists()
        if path.is_dir():
            raise ToolExecutionError("not a file: " + str(path))
        if args.create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        previous = path.read_text(encoding="utf-8") if existed else ""
        path.write_text(args.content, encoding="utf-8")
        verb = "updated" if existed else "created"
        return ToolOutcome(
            output=verb + " " + str(path) + " (" + str(len(args.content)) + " chars)",
            data={
                "path": str(path),
                "created": not existed,
                "bytes": len(args.content.encode("utf-8")),
                "replaced_chars": len(previous),
            },
        )

    @tools.tool(
        "apply_patch",
        "Replace exact text fragments inside a file (no whole-file rewrite).",
        ApplyPatchArgs,
        risk="medium",
        idempotent=False,
    )
    def apply_patch(args: ApplyPatchArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        path = active.resolve(args.path)
        if not path.exists():
            if not args.create_if_missing:
                raise ToolExecutionError("no such file: " + str(path))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        if not args.hunks:
            raise ToolValidationError("at least one hunk is required")

        text = path.read_text(encoding="utf-8")
        applied = 0
        for number, hunk in enumerate(args.hunks, start=1):
            occurrences = text.count(hunk.old)
            if occurrences == 0:
                raise ToolExecutionError(
                    "hunk "
                    + str(number)
                    + " did not match any text in "
                    + str(path)
                    + "; nothing was written"
                )
            if occurrences > 1:
                raise ToolExecutionError(
                    "hunk "
                    + str(number)
                    + " matches "
                    + str(occurrences)
                    + " places in "
                    + str(path)
                    + "; make the anchor unique (nothing was written)"
                )
            text = text.replace(hunk.old, hunk.new, 1)
            applied += 1

        path.write_text(text, encoding="utf-8")
        return ToolOutcome(
            output="applied " + str(applied) + " hunk(s) to " + str(path),
            data={"path": str(path), "hunks": applied, "bytes": len(text.encode("utf-8"))},
        )

    @tools.tool(
        "search",
        "Search file contents with a regular expression.",
        SearchArgs,
        risk="low",
        idempotent=True,
    )
    def search(args: SearchArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        root = active.resolve(args.path)
        if not root.exists():
            raise ToolExecutionError("no such path: " + str(root))
        try:
            flags = re.IGNORECASE if args.ignore_case else 0
            pattern = re.compile(args.pattern, flags)
        except re.error as exc:
            raise ToolValidationError("invalid regular expression: " + str(exc)) from exc

        matches: list[str] = []
        files_scanned = 0
        truncated = False

        candidates = [root] if root.is_file() else None
        iterator = candidates if candidates is not None else _walk_files(root)

        for file_path in iterator:
            if len(matches) >= args.max_results:
                truncated = True
                break
            if args.include and not fnmatch.fnmatch(file_path.name, args.include):
                continue
            if not root.is_file() and any(part in SKIPPED_DIRECTORIES for part in file_path.parts):
                continue
            files_scanned += 1
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(str(file_path) + ":" + str(number) + ": " + line.strip()[:200])
                    if len(matches) >= args.max_results:
                        truncated = True
                        break

        header = (
            str(len(matches))
            + " match(es) in "
            + str(files_scanned)
            + " file(s) under "
            + str(root)
        )
        if truncated:
            header += " [truncated]"
        return ToolOutcome(
            output=clip_output(header + "\n" + "\n".join(matches)),
            data={
                "matches": len(matches),
                "files_scanned": files_scanned,
                "truncated": truncated,
            },
        )

    @tools.tool(
        "run_shell",
        "Run a shell command and capture its output.",
        RunShellArgs,
        risk="high",
        requires_confirmation=True,
    )
    def run_shell(args: RunShellArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        cwd = active.resolve(args.cwd) if args.cwd else active.working_dir
        if not cwd.is_dir():
            raise ToolExecutionError("working directory does not exist: " + str(cwd))
        started = time.monotonic()
        try:
            # Popen + communicate rather than subprocess.run: on Windows the
            # timeout of run() kills only the shell, and a grandchild that
            # inherited the stdout pipe keeps it open, so communicate() waits
            # forever. A generated test that starts an HTTP server hung a real
            # run for minutes with the whole run frozen behind it. Here the
            # process TREE is killed, which is what closes the pipe.
            process = subprocess.Popen(
                args.command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise ToolExecutionError(
                "could not run the command: " + str(exc), retryable=True
            ) from exc

        try:
            stdout, stderr = process.communicate(timeout=args.timeout_ms / 1000)
        except subprocess.TimeoutExpired as exc:
            kill_process_tree(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - pipes held open
                pass
            # A timeout is the one shell failure worth another attempt.
            raise ToolExecutionError(
                "command timed out after "
                + str(args.timeout_ms)
                + " ms (the process tree was killed)",
                retryable=True,
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        completed = subprocess.CompletedProcess(
            args.command, process.returncode, stdout, stderr
        )
        body = ""
        if completed.stdout:
            body += "stdout:\n" + completed.stdout
        if completed.stderr:
            body += ("\n" if body else "") + "stderr:\n" + completed.stderr
        if not body:
            body = "(no output)"
        header = (
            "$ "
            + args.command
            + "\n(cwd "
            + str(cwd)
            + ", exit "
            + str(completed.returncode)
            + ", "
            + str(duration_ms)
            + " ms)"
        )
        return ToolOutcome(
            output=clip_output(header + "\n" + body),
            data={
                "exit_code": completed.returncode,
                "duration_ms": duration_ms,
                "cwd": str(cwd),
            },
        )

    @tools.tool(
        "memory_propose",
        "Propose one long-lived memory; the system reviews it before storing.",
        MemoryProposeArgs,
        risk="medium",
    )
    def memory_propose(
        args: MemoryProposeArgs, context: ToolContext | None = None
    ) -> ToolOutcome:
        active = ctx_for(context)
        store = active.memory or MemoryStore(active.store)
        decision = store.propose(
            MemoryProposal(
                key=args.key,
                value=args.value,
                namespace=args.namespace,
                reason=args.reason or "memory_propose",
                proposed_by="model",
            )
        )
        detail = decision.decision + ": " + decision.reason
        if decision.decision not in ("accepted", "updated"):
            raise ToolExecutionError("memory not stored — " + detail)
        return ToolOutcome(
            output="memory " + detail,
            data={"decision": decision.decision, "key": decision.stored_key},
        )

    @tools.tool(
        "update_project_state",
        "Update the persisted project state (only the fields provided change).",
        UpdateProjectStateArgs,
        risk="medium",
        idempotent=True,
    )
    def update_project_state(
        args: UpdateProjectStateArgs, context: ToolContext | None = None
    ) -> ToolOutcome:
        active = ctx_for(context)
        state = active.store.load_project_state()
        changed: list[str] = []

        for field_name in (
            "current_milestone",
            "current_task",
            "goal",
            "checkpoint",
            "git_branch",
        ):
            value = getattr(args, field_name)
            if value is not None and getattr(state, field_name) != value:
                setattr(state, field_name, value)
                changed.append(field_name)

        if args.add_files_changed:
            for item in args.add_files_changed:
                if item not in state.files_changed:
                    state.files_changed.append(item)
                    changed.append("files_changed+" + item)
        if args.add_decisions:
            for item in args.add_decisions:
                if item not in state.decisions:
                    state.decisions.append(item)
                    changed.append("decisions+" + item[:40])
        if args.add_failures:
            for item in args.add_failures:
                state.failures.append(item)
                changed.append("failures+" + item[:40])
        if args.add_test_result:
            state.tests.append(args.add_test_result)
            changed.append("tests+" + args.add_test_result[:40])
        if args.set_todos is not None:
            state.todos = list(args.set_todos)
            changed.append("todos")

        active.store.save_project_state(state)
        summary = (
            "project state updated: " + ", ".join(changed)
            if changed
            else "project state unchanged (no new values)"
        )
        return ToolOutcome(
            output=summary,
            data={"changed": changed, "milestone": state.current_milestone},
        )

    @tools.tool(
        "ask_user",
        "Ask the human a question and wait for the answer.",
        AskUserArgs,
        risk="low",
    )
    def ask_user(args: AskUserArgs, context: ToolContext | None = None) -> ToolOutcome:
        active = ctx_for(context)
        if active.user_resolver is None:
            raise ToolExecutionError(
                "no user channel is available; the question was not delivered"
            )
        answer = active.user_resolver(args.question)
        return ToolOutcome(
            output="user answered: " + answer,
            data={"question": args.question, "answer": answer},
        )

    return tools


def _walk_files(root: Path):
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if name not in SKIPPED_DIRECTORIES
        ]
        for name in files:
            yield Path(directory) / name


def default_registry() -> ToolRegistry:
    return build_default_registry()
