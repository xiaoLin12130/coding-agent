"""Live project build: let the coding agent develop a real project by itself.

Not collected by pytest (the filename is not test_*.py): it opens a headed
browser, talks to a real web LLM and runs for tens of minutes.

    cd backend
    ../.venv/Scripts/python.exe tests/manual/live_project_build.py \
        --workspace H:/AI-game/library-live \
        --task-file H:/AI-game/library-live/TASK.md \
        --max-steps 30

What it does:

* creates/reuses a workspace and a state directory inside it,
* selects the BROWSER provider (a real web LLM) through the settings document,
* runs the real AgentLoop in that workspace: parser -> SafetyLayer -> Executor,
* answers high-risk confirmations according to the confirmation policy,
* streams every event to stdout and to events.jsonl in the workspace.

The point is not that the run succeeds - it is to see what a real model does
with a real project and to record where the agent system gets in its way.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.agents.checkpoint import CheckpointStore
from app.agents.loop import DEFAULT_SYSTEM, AgentLoop
from app.agents.models import LoopLimits
from app.config import AppPaths
from app.console_model import ConsoleModel
from app.context import ContextBuilder, SessionManager
from app.safety import SafetyLayer
from app.settings import SettingsStore
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="live_project_build")
    parser.add_argument("--workspace", required=True, help="project directory to build in")
    parser.add_argument("--task", default="", help="the task text")
    parser.add_argument("--task-file", default="", help="read the task from this file")
    parser.add_argument("--profile", default="deepseek-web", help="browser provider profile")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--timeout-minutes", type=int, default=60)
    parser.add_argument("--policy", default="auto_once", choices=("ask", "auto_once", "deny"))
    parser.add_argument("--system", default="", help="override the system prompt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = pathlib.Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    task = args.task
    if args.task_file:
        task = pathlib.Path(args.task_file).read_text(encoding="utf-8")
    if not task.strip():
        raise SystemExit("a task is required (--task or --task-file)")

    state_dir = workspace / ".agent"
    state_dir.mkdir(parents=True, exist_ok=True)
    settings_path = state_dir / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "working_dir": str(workspace),
                "provider": {"adapter": "browser", "name": args.profile},
                "browser": {"profile_dir": str(pathlib.Path(
                    os.environ.get("CODING_AGENT_BROWSER_PROFILE_DIR", "")
                ) or pathlib.Path(__file__).resolve().parents[3] / ".browser-profile")},
                "confirmation": {"policy": args.policy, "ttl_seconds": 600},
            }
        ),
        encoding="utf-8",
    )

    paths = AppPaths(
        project_root=workspace,
        state_dir=state_dir,
        project_state_file=state_dir / "project_state.json",
        memory_file=state_dir / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(working_dir=workspace, store=store)
    executor = Executor(
        build_default_registry(context),
        context,
        log_path=workspace / "runs" / "tool-calls.jsonl",
    )
    sessions = SessionManager(state_dir / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    safety = SafetyLayer.for_project(workspace)
    checkpoints = CheckpointStore(state_dir / "checkpoints")

    settings = SettingsStore(settings_path)
    policy = settings.load().confirmation.policy
    model = ConsoleModel(settings).model()

    event_log = (state_dir / "events.jsonl").open("w", encoding="utf-8")
    started = time.monotonic()

    def on_event(event) -> None:
        event_log.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
        event_log.flush()
        elapsed = int(time.monotonic() - started)
        line = event.render()[:220]
        print(f"[{elapsed:5d}s] " + line, flush=True)

    def confirm(request) -> str:
        tool = (request or {}).get("tool")
        print(f"          confirmation asked for {tool}: policy={policy}", flush=True)
        return "once" if policy == "auto_once" else "reject"

    loop = AgentLoop(
        model,
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(
            max_steps=args.max_steps,
            timeout_ms=args.timeout_minutes * 60_000,
            max_parse_retries=2,
            max_tool_retries=2,
        ),
        checkpoints=checkpoints,
        safety=safety,
        system=args.system or DEFAULT_SYSTEM,
        on_event=on_event,
        confirm=confirm,
        working_dir=workspace,
        thresholds=None,
    )

    print("workspace :", workspace, flush=True)
    print("provider  :", args.profile, "| policy:", policy, "| max steps:", args.max_steps, flush=True)
    print("-" * 70, flush=True)

    result = loop.run(task)
    event_log.close()

    print("-" * 70)
    print("status      :", result.status)
    print("reason      :", result.reason)
    print("steps       :", result.step_count)
    print("tool calls  :", result.tool_calls, "(" + str(result.tool_failures) + " failed)")
    print("tools       :", json.dumps(result.tool_summary()))
    print("duration    :", result.duration_ms, "ms")
    print("final       :", (result.final_message or "")[:500])
    print("checkpoint  :", result.checkpoint_path)
    print("events      :", state_dir / "events.jsonl")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
