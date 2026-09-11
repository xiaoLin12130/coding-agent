"""Recovery command line (M6).

    cd backend
    python -m app.recovery.cli status                      # what a restart would find
    python -m app.recovery.cli pressure --task "..."       # context pressure
    python -m app.recovery.cli runs                        # unfinished runs
    python -m app.recovery.cli resume --run-id R --script plan.json
    python -m app.recovery.cli rotate --reason context_budget
    python -m app.recovery.cli browser --profile mock      # page + login state

Everything goes through the same components the loop uses; nothing bypasses the
SafetyLayer or the Executor.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agents.checkpoint import CheckpointStore
from ..agents.cli import _build as build_loop_cli  # reuse the loop assembly
from ..agents.llm import ScriptedModel
from ..agents.loop import AgentLoop
from ..config import runs_dir
from ..context import ContextBuilder, SessionManager
from ..recovery import (
    BrowserRecovery,
    ContextPressurePolicy,
    RunRecovery,
    SessionRecovery,
    build_snapshot,
)
from ..recovery.models import ContextThresholds
from ..storage import StateStore
from ..tools import Executor, ToolContext, build_default_registry


def _sessions(args: argparse.Namespace) -> SessionManager:
    return SessionManager(args.sessions_dir, store=StateStore())


def _cmd_status(args: argparse.Namespace) -> int:
    snapshot = build_snapshot(
        sessions=_sessions(args),
        checkpoints=CheckpointStore(args.checkpoints_dir),
        task=args.task,
        system=args.system,
    )
    if args.json:
        print(json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    print("active session : " + str(snapshot.active_session_id))
    print("messages       : " + str(snapshot.session_message_count))
    print("archived       : " + (", ".join(snapshot.archived_session_ids) or "none"))
    print("memory entries : " + str(snapshot.memory_count))
    if snapshot.latest_run is not None:
        run = snapshot.latest_run
        state = "resumable" if run.resumable else "finished"
        print("latest run     : " + run.run_id + " (" + state + ", step " + str(run.step) + ")")
        print("  task         : " + run.task[:100])
        if run.reason:
            print("  note         : " + run.reason)
    else:
        print("latest run     : none")
    if snapshot.context_pressure is not None:
        pressure = snapshot.context_pressure
        print(
            "context        : "
            + pressure.level
            + " ("
            + str(pressure.used_chars)
            + "/"
            + str(pressure.budget_chars)
            + ", "
            + str(round(pressure.ratio * 100, 1))
            + "%)"
        )
    return 0


def _cmd_pressure(args: argparse.Namespace) -> int:
    sessions = _sessions(args)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    snapshot = sessions.start()
    context = builder.build(
        session_id=snapshot.active_session_id or "", system=args.system, task=args.task
    )
    policy = ContextPressurePolicy(
        ContextThresholds(soft_ratio=args.soft, hard_ratio=args.hard)
    )
    pressure = policy.evaluate(context, builder.budget.max_chars)
    if args.json:
        print(json.dumps(pressure.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    print(
        pressure.level.upper()
        + ": "
        + str(pressure.used_chars)
        + "/"
        + str(pressure.budget_chars)
        + " chars ("
        + str(round(pressure.ratio * 100, 1))
        + "%)"
    )
    if pressure.dropped_sections:
        print("dropped: " + ", ".join(pressure.dropped_sections))
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    recovery = RunRecovery(CheckpointStore(args.checkpoints_dir), _sessions(args))
    plans = recovery.pending()
    if args.json:
        print(json.dumps([plan.model_dump(mode="json") for plan in plans], indent=2, ensure_ascii=False))
        return 0
    if not plans:
        print("no unfinished runs")
        return 0
    for plan in plans:
        print(plan.run_id.ljust(14) + " step=" + str(plan.step) + " " + plan.task[:70])
        if plan.reason:
            print("    note: " + plan.reason)
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    sessions = _sessions(args)
    store = StateStore()
    working_dir = Path(args.working_dir).resolve() if args.working_dir else Path.cwd()
    context = ToolContext(working_dir=working_dir, store=store)
    executor = Executor(
        build_default_registry(context),
        context,
        log_path=Path(args.log) if args.log else runs_dir() / "tool-calls.jsonl",
    )

    script: list[str] = []
    if args.script:
        raw = json.loads(Path(args.script).read_text(encoding="utf-8"))
        script = list(raw.get("replies", [])) if isinstance(raw, dict) else [str(x) for x in raw]

    from ..agents.models import LoopLimits

    loop = AgentLoop(
        ScriptedModel(script, final_message=args.final),
        executor,
        sessions,
        builder=ContextBuilder(sessions.transcript, sessions.memory, sessions.store),
        limits=LoopLimits(max_steps=args.max_steps, timeout_ms=args.timeout_ms),
        checkpoints=CheckpointStore(args.checkpoints_dir),
        confirm=(lambda request: args.confirm) if args.confirm else None,
        working_dir=working_dir,
        # A --script supplied for this invocation is a fresh model: starting it
        # at the checkpoint's old index would silently skip the first reply.
        restore_model_state=not script,
    )

    recovery = RunRecovery(CheckpointStore(args.checkpoints_dir), sessions)
    result, report = recovery.resume(loop, run_id=args.run_id)

    if args.json:
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "result": result.model_dump(mode="json") if result is not None else None,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(report.render())
        if result is not None:
            print()
            print("status    : " + result.status)
            print("steps     : " + str(result.step_count))
            print("tools     : " + json.dumps(result.tool_summary()))
            if result.final_message:
                print("final     : " + result.final_message[:300])
    return 0 if report.recovered else 1


def _cmd_rotate(args: argparse.Namespace) -> int:
    sessions = _sessions(args)
    recovery = SessionRecovery(sessions)
    report = recovery.rotate(reason=args.reason)
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    print(report.render())
    return 0 if report.recovered else 1


def _cmd_browser(args: argparse.Namespace) -> int:
    """Open a profile and report whether the page and the login are usable."""
    from ..browser.artifacts import ArtifactStore
    from ..browser.driver import BrowserDriver
    from ..browser.profiles import load_profile
    from ..browser.web_chat import WebChatProvider

    profile = load_profile(args.profile, args.profiles_dir)

    def factory():
        driver = BrowserDriver(
            profile_dir=args.profile_dir,
            artifacts=ArtifactStore(base_dir=args.artifacts_dir, run_name=profile.name),
        ).start()
        provider = WebChatProvider(driver, profile)
        wrapper = type("Session", (), {})()
        wrapper.driver = driver
        wrapper.provider = provider
        wrapper.close = driver.close
        return wrapper

    recovery = BrowserRecovery(factory, login_timeout_ms=args.timeout * 1000)
    session = recovery.session
    try:
        session.provider.open()
        report = recovery.ensure_ready(timeout_ms=args.timeout * 1000)
        payload = {
            "profile": profile.name,
            "url": profile.url,
            "alive": recovery.is_alive(),
            "report": report.model_dump(mode="json"),
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(report.render())
        return 0 if not report.failed else 1
    finally:
        recovery.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.recovery.cli")
    parser.add_argument("--sessions-dir", default=None)
    parser.add_argument("--checkpoints-dir", default=None)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="what a restart would find")
    p.add_argument("--task", default="")
    p.add_argument("--system", default="")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("pressure", help="context pressure for the next turn")
    p.add_argument("--task", default="")
    p.add_argument("--system", default="You are a helpful software engineer assistant.")
    p.add_argument("--soft", type=float, default=0.7)
    p.add_argument("--hard", type=float, default=0.9)
    p.set_defaults(func=_cmd_pressure)

    p = sub.add_parser("runs", help="list unfinished runs")
    p.set_defaults(func=_cmd_runs)

    p = sub.add_parser("resume", help="continue a run after a restart")
    p.add_argument("--run-id", default=None)
    p.add_argument("--script", default=None)
    p.add_argument("--final", default="Done.")
    p.add_argument("--working-dir", default=None)
    p.add_argument("--log", default=None)
    p.add_argument("--max-steps", type=int, default=25)
    p.add_argument("--timeout-ms", type=int, default=600_000)
    p.add_argument("--confirm", default=None, choices=["reject", "once", "session"])
    p.set_defaults(func=_cmd_resume)

    p = sub.add_parser("rotate", help="run the Context-full sequence now")
    p.add_argument("--reason", default="manual")
    p.set_defaults(func=_cmd_rotate)

    p = sub.add_parser("browser", help="check a browser profile and its login")
    p.add_argument("--profile", required=True)
    p.add_argument("--profiles-dir", default=None)
    p.add_argument("--profile-dir", default=None)
    p.add_argument("--artifacts-dir", default=None)
    p.add_argument("--timeout", type=int, default=300, help="login wait in seconds")
    p.set_defaults(func=_cmd_browser)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
