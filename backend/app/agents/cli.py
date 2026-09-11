"""Agent loop command line (M5).

    cd backend
    python -m app.agents.cli run --task "fix the failing test" --script plan.json
    python -m app.agents.cli run --task "..." --script plan.json --confirm once
    python -m app.agents.cli resume --run RUN_ID
    python -m app.agents.cli checkpoints

'--script' is a JSON file with the model's canned replies; it exists so the
loop can be exercised without a web LLM. Every tool call still goes through the
parser, the SafetyLayer and the Executor — the CLI bypasses nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import runs_dir
from ..context import ContextBuilder, SessionManager
from ..storage import StateStore
from ..tools import Executor, ToolContext, build_default_registry
from .checkpoint import CheckpointStore
from .llm import ScriptedModel
from .loop import DEFAULT_SYSTEM, AgentLoop
from .models import LoopLimits

CHOICES = ("reject", "once", "session")


def _build(args: argparse.Namespace):
    working_dir = Path(args.working_dir).resolve() if args.working_dir else Path.cwd()
    store = StateStore()
    context = ToolContext(working_dir=working_dir, store=store)
    executor = Executor(
        build_default_registry(context),
        context,
        log_path=Path(args.log) if args.log else runs_dir() / "tool-calls.jsonl",
    )
    sessions = SessionManager(args.sessions_dir, store=store)
    checkpoints = CheckpointStore(args.checkpoints_dir)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)

    script: list[str] = []
    if getattr(args, "script", None):
        raw = json.loads(Path(args.script).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            script = list(raw.get("replies", []))
        elif isinstance(raw, list):
            script = [str(item) for item in raw]
        else:
            raise SystemExit("the script file must be a list or {\"replies\": [...]}")

    model = ScriptedModel(script, final_message=args.final or "Done.")

    limit_kwargs = {
        "max_steps": args.max_steps,
        "timeout_ms": args.timeout_ms,
        "max_tool_retries": args.max_tool_retries,
        "max_parse_retries": args.max_parse_retries,
    }
    limits = LoopLimits(**limit_kwargs)

    def confirm(request) -> str:
        print("-" * 60)
        if isinstance(request, dict):
            for key in ("tool", "risk", "command", "cwd", "impact", "reasons", "choices"):
                if key in request:
                    print(key.ljust(8) + ": " + str(request[key]))
        else:  # pragma: no cover - defensive
            print(str(request))
        print("-" * 60)
        if args.confirm:
            return args.confirm
        answer = input("1) reject  2) once  3) session  [1]: ").strip() or "1"
        return {"1": "reject", "2": "once", "3": "session"}.get(answer, answer)

    def on_event(event):
        if args.quiet:
            return
        print("  " + event.render()[:200])

    loop = AgentLoop(
        model,
        executor,
        sessions,
        builder=builder,
        limits=limits,
        checkpoints=checkpoints,
        system=args.system or DEFAULT_SYSTEM,
        on_event=on_event,
        confirm=confirm if (args.confirm or not args.no_confirm) else None,
        working_dir=working_dir,
    )
    return loop, sessions


def _cmd_run(args: argparse.Namespace) -> int:
    loop, _sessions = _build(args)
    result = loop.run(args.task, run_id=args.run_id)
    return _report(result, args)


def _cmd_resume(args: argparse.Namespace) -> int:
    loop, _sessions = _build(args)
    if args.task is None:
        store = CheckpointStore(args.checkpoints_dir)
        checkpoint = store.load(args.run_id)
        if checkpoint is None:
            print("no checkpoint for run " + args.run_id, file=sys.stderr)
            return 2
        args.task = checkpoint.task
    result = loop.run(args.task, run_id=args.run_id, resume=True)
    return _report(result, args)


def _report(result, args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        print()
        print("status    : " + result.status)
        print("reason    : " + result.reason)
        print("steps     : " + str(result.step_count))
        print("tool calls: " + str(result.tool_calls) + " (" + str(result.tool_failures) + " failed)")
        print("tools     : " + json.dumps(result.tool_summary()))
        print("duration  : " + str(result.duration_ms) + " ms")
        if result.final_message:
            print("final     : " + result.final_message[:400])
        print("checkpoint: " + str(result.checkpoint_path))
    return 0 if result.status == "completed" else 1


def _cmd_roles(args: argparse.Namespace) -> int:
    """Show the six roles and the tools each one may use."""
    from .roles import DEFAULT_ROLES

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": role.name,
                        "purpose": role.purpose,
                        "allowed_tools": role.allowed_tools,
                        "max_steps": role.max_steps,
                        "verdict": role.verdict_kind,
                    }
                    for role in DEFAULT_ROLES.values()
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(str(len(DEFAULT_ROLES)) + " role(s):")
    for role in DEFAULT_ROLES.values():
        print("  " + role.name.ljust(16) + role.purpose)
        print("      tools: " + (", ".join(role.allowed_tools) or "(none)"))
    return 0


def _cmd_orchestrate(args: argparse.Namespace) -> int:
    """Run the Planner -> Coder -> Reviewer collaboration."""
    from .models import OrchestrationResult  # noqa: F401  (documentation)
    from .orchestrator import AgentOrchestrator, OrchestrationLimits
    from .roles import DEFAULT_ROLES

    working_dir = Path(args.working_dir).resolve() if args.working_dir else Path.cwd()
    store = StateStore()
    context = ToolContext(working_dir=working_dir, store=store)
    registry = build_default_registry(context)
    sessions = SessionManager(args.sessions_dir, store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    checkpoints = CheckpointStore(args.checkpoints_dir)

    # A script may be one reply list shared by every role, or a mapping of
    # role -> replies, which multi-call roles need to stay deterministic.
    per_role: dict[str, list[str]] = {}
    shared: list[str] = []
    if args.script:
        raw = json.loads(Path(args.script).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "replies" not in raw:
            per_role = {str(name): [str(x) for x in replies] for name, replies in raw.items()}
        elif isinstance(raw, dict):
            shared = list(raw.get("replies", []))
        else:
            shared = [str(x) for x in raw]

    def make_model(role) -> ScriptedModel:
        return ScriptedModel(
            per_role.get(role.name, shared), final_message=args.final, name=role.name
        )

    model = ScriptedModel(shared, final_message=args.final)

    limits = OrchestrationLimits(
        max_rounds=args.max_rounds,
        max_steps=args.max_steps_per_role,
        timeout_ms=args.timeout_ms,
        stall_threshold=args.stall_threshold,
    )

    def confirm(request) -> str:
        if args.confirm:
            return args.confirm
        if isinstance(request, dict):
            print("-" * 60)
            for key in ("tool", "risk", "command", "cwd", "impact", "choices"):
                if key in request:
                    print(key.ljust(8) + ": " + str(request[key]))
            print("-" * 60)
        answer = input("1) reject  2) once  3) session  [1]: ").strip() or "1"
        return {"1": "reject", "2": "once", "3": "session"}.get(answer, answer)

    def on_event(event) -> None:
        if not args.quiet:
            print("  " + event.render()[:200])

    orchestrator = AgentOrchestrator(
        model if not per_role else None,
        sessions,
        context,
        model_factory=make_model if per_role else None,
        builder=builder,
        limits=limits,
        registry=registry,
        on_event=on_event,
        confirm=confirm if (args.confirm or not args.no_confirm) else None,
        log_path=Path(args.log) if args.log else runs_dir() / "tool-calls.jsonl",
    )

    result = orchestrator.run(args.task, run_id=args.run_id)

    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1

    print()
    print("status    : " + result.status)
    print("reason    : " + result.reason)
    print("rounds    : " + str(result.round_count) + " of " + str(limits.max_rounds))
    print("roles     : " + json.dumps(result.role_summary()))
    print("tools     : " + str(result.tool_calls) + " (" + str(result.tool_failures) + " failed)")
    for role, tools in result.tools_by_role().items():
        if tools:
            print("  " + role + ": " + ", ".join(sorted(set(tools))))
    for index, record in enumerate(result.rounds, start=1):
        verdict = record.verdict
        issues = "; ".join(record.issues[:2])
        print("round " + str(index) + ": reviewer -> " + verdict + (" (" + issues + ")" if issues else ""))
    if result.plan:
        print("plan      :")
        for line in result.plan.splitlines()[:8]:
            print("  " + line)
    return 0 if result.ok else 1


def _cmd_checkpoints(args: argparse.Namespace) -> int:
    store = CheckpointStore(args.checkpoints_dir)
    runs = store.runs()
    if args.json:
        print(json.dumps([store.load(run).model_dump(mode="json") for run in runs if store.load(run)], indent=2, ensure_ascii=False))
        return 0
    if not runs:
        print("no checkpoints")
        return 0
    for run in runs:
        checkpoint = store.load(run)
        if checkpoint is None:
            continue
        print(
            run.ljust(14)
            + " step=" + str(checkpoint.step)
            + " status=" + str(checkpoint.status)
            + " task=" + checkpoint.task[:60]
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.agents.cli")
    parser.add_argument("--working-dir", default=None)
    parser.add_argument("--sessions-dir", default=None)
    parser.add_argument("--checkpoints-dir", default=None)
    parser.add_argument("--log", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="do not stream events")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one task through the loop")
    run.add_argument("--task", required=True)
    run.add_argument("--script", default=None, help="JSON file of canned model replies")
    run.add_argument("--final", default="Done.", help="reply used once the script runs out")
    run.add_argument("--system", default=None)
    run.add_argument("--run-id", default=None)
    run.add_argument("--max-steps", type=int, default=25)
    run.add_argument("--timeout-ms", type=int, default=600_000)
    run.add_argument("--max-tool-retries", type=int, default=2)
    run.add_argument("--max-parse-retries", type=int, default=2)
    run.add_argument("--confirm", default=None, choices=list(CHOICES))
    run.add_argument("--no-confirm", action="store_true", help="never ask; refusals go back to the model")
    run.set_defaults(func=_cmd_run)

    resume = sub.add_parser("resume", help="continue a run from its checkpoint")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--task", default=None)
    resume.add_argument("--script", default=None)
    resume.add_argument("--final", default="Done.")
    resume.add_argument("--system", default=None)
    resume.add_argument("--max-steps", type=int, default=25)
    resume.add_argument("--timeout-ms", type=int, default=600_000)
    resume.add_argument("--max-tool-retries", type=int, default=2)
    resume.add_argument("--max-parse-retries", type=int, default=2)
    resume.add_argument("--confirm", default=None, choices=list(CHOICES))
    resume.add_argument("--no-confirm", action="store_true")
    resume.set_defaults(func=_cmd_resume)

    checkpoints = sub.add_parser("checkpoints", help="list run checkpoints")
    checkpoints.set_defaults(func=_cmd_checkpoints)

    roles = sub.add_parser("roles", help="show the runtime roles and their tools")
    roles.set_defaults(func=_cmd_roles)

    orchestrate = sub.add_parser(
        "orchestrate", help="run the Planner -> Coder -> Reviewer collaboration"
    )
    orchestrate.add_argument("--task", required=True)
    orchestrate.add_argument(
        "--script",
        default=None,
        help='JSON of canned replies: {"replies": [...]} shared by every role, '
        'or {"planner": [...], "coder": [...], ...} per role',
    )
    orchestrate.add_argument("--final", default="Done.")
    orchestrate.add_argument("--run-id", default=None)
    orchestrate.add_argument("--max-rounds", type=int, default=3)
    orchestrate.add_argument("--stall-threshold", type=int, default=2)
    orchestrate.add_argument("--max-steps-per-role", type=int, default=25)
    orchestrate.add_argument("--timeout-ms", type=int, default=600_000)
    orchestrate.add_argument("--confirm", default=None, choices=list(CHOICES))
    orchestrate.add_argument(
        "--no-confirm", action="store_true", help="never ask; refusals go back to the role"
    )
    orchestrate.set_defaults(func=_cmd_orchestrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
