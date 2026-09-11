"""Tool layer command line (M3).

    cd backend
    python -m app.tools.cli list                         # the catalogue
    python -m app.tools.cli schema read_file             # one JSON schema
    python -m app.tools.cli parse --text '{"name": ...}' # parser demo
    python -m app.tools.cli run read_file --args '{"path": "README.md"}'
    python -m app.tools.cli run run_shell --args '{"command": "echo hi"}' --confirm

Every invocation goes through the Executor, so the CLI uses exactly the same
path as the model will: schema validation, the confirmation seam, logging and
idempotency. It deliberately bypasses nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import runs_dir
from ..context.memory import MemoryStore
from ..storage import StateStore
from .builtin import ToolContext, build_default_registry
from .executor import Executor
from .models import ToolCall
from .parser import parse_tool_calls


def _context(working_dir: Path | None) -> ToolContext:
    store = StateStore()
    return ToolContext(
        working_dir=Path(working_dir) if working_dir else Path.cwd(),
        store=store,
        memory=MemoryStore(store),
        user_resolver=lambda question: input(question + " "),
    )


def _executor(args: argparse.Namespace) -> Executor:
    context = _context(args.working_dir)
    registry = build_default_registry(context)
    log_path = Path(args.log) if args.log else runs_dir() / "tool-calls.jsonl"
    return Executor(registry, context, log_path=log_path)


def _cmd_list(args: argparse.Namespace) -> int:
    executor = _executor(args)
    specs = executor.registry.specs()
    if args.json:
        print(json.dumps(executor.registry.schemas(), indent=2, ensure_ascii=False))
        return 0
    print(str(len(specs)) + " tool(s):")
    for spec in sorted(specs, key=lambda s: s.name):
        flags = []
        if spec.risk != "low":
            flags.append("risk=" + spec.risk)
        if spec.requires_confirmation:
            flags.append("needs confirmation")
        if spec.idempotent:
            flags.append("idempotent")
        suffix = ("  [" + ", ".join(flags) + "]") if flags else ""
        print("  " + spec.name.ljust(22) + spec.description + suffix)
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    executor = _executor(args)
    tool = executor.registry.get(args.name)
    print(json.dumps(tool.spec.parameters, indent=2, ensure_ascii=False))
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    text = args.text if args.text is not None else sys.stdin.read()
    known = set(_executor(args).registry.names()) if not args.any_tool else None
    outcome = parse_tool_calls(text, known_tools=known)
    if args.json:
        print(json.dumps(outcome.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0 if outcome.calls else 1
    print("format: " + outcome.format)
    for call in outcome.calls:
        print("  call " + str(call.index) + ": " + call.name + " " + json.dumps(call.arguments, ensure_ascii=False))
    for issue in outcome.issues:
        print("  issue " + issue.code + ": " + issue.message)
        print("    fix: " + issue.repair_hint)
    return 0 if outcome.calls and not outcome.issues else 1


def _cmd_run(args: argparse.Namespace) -> int:
    executor = _executor(args)
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print("--args must be JSON: " + str(exc), file=sys.stderr)
        return 2
    if not isinstance(arguments, dict):
        print("--args must be a JSON object", file=sys.stderr)
        return 2

    call = ToolCall(id="cli-1", name=args.name, arguments=arguments)
    result = executor.execute(call, confirmed=args.confirm)

    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        print(result.output if result.ok else "FAILED " + result.error.code + ": " + result.error.message)
        if result.data:
            print("data: " + json.dumps(result.data, ensure_ascii=False))
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.tools.cli")
    parser.add_argument("--working-dir", default=None, help="directory tools resolve paths against")
    parser.add_argument("--log", default=None, help="tool call log path (default runs/tool-calls.jsonl)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list the tool catalogue")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("schema", help="print one tool's argument schema")
    p.add_argument("name")
    p.set_defaults(func=_cmd_schema)

    p = sub.add_parser("parse", help="parse model output into tool calls")
    p.add_argument("--text", default=None, help="text to parse (default: stdin)")
    p.add_argument("--any-tool", action="store_true", help="do not check the tool name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_parse)

    p = sub.add_parser("run", help="run one tool through the Executor")
    p.add_argument("name")
    p.add_argument("--args", default="{}", help="JSON object of arguments")
    p.add_argument("--confirm", action="store_true", help="confirm a confirmation-required tool")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
