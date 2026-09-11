"""Safety command line (M4).

    cd backend
    python -m app.safety.cli check-path --path ../outside.txt
    python -m app.safety.cli grade --command "rm -rf /"
    python -m app.safety.cli scan --text "IGNORE ALL PREVIOUS INSTRUCTIONS"
    python -m app.safety.cli assess --tool run_shell --args '{"command": "echo hi"}'
    python -m app.safety.cli confirm --tool run_shell --args '{"command": "echo hi"}'

'confirm' is the terminal rendering of the confirmation UI: it shows the four
facts docs/safety.md requires (command, cwd, impact, risk) and offers the three
choices (reject / once / session), then runs the call through the same Executor
the model would use.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import runs_dir
from ..context.memory import MemoryStore
from ..storage import StateStore
from ..tools import Executor, ToolCall, ToolContext, build_default_registry
from .injection import scan_untrusted
from .layer import SafetyLayer
from .paths import FilesystemPolicy
from .shell import ShellGrader

CHOICE_LABELS = {
    "1": "reject",
    "2": "once",
    "3": "session",
}


def _layer(args: argparse.Namespace) -> SafetyLayer:
    root = Path(args.project).resolve() if args.project else Path.cwd()
    return SafetyLayer.for_project(root)


def _context(args: argparse.Namespace) -> ToolContext:
    store = StateStore()
    root = Path(args.project).resolve() if args.project else Path.cwd()
    return ToolContext(
        working_dir=root,
        store=store,
        memory=MemoryStore(store),
        user_resolver=lambda question: input(question + " "),
    )


def _executor(args: argparse.Namespace, layer: SafetyLayer) -> Executor:
    context = _context(args)
    log_path = Path(args.log) if args.log else runs_dir() / "tool-calls.jsonl"
    return Executor(
        build_default_registry(context), context, log_path=log_path, safety=layer
    )


def _call(args: argparse.Namespace) -> ToolCall:
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        raise SystemExit("--args must be JSON: " + str(exc))
    if not isinstance(arguments, dict):
        raise SystemExit("--args must be a JSON object")
    return ToolCall(id="cli-1", name=args.tool, arguments=arguments)


# --- commands -------------------------------------------------------------


def _cmd_check_path(args: argparse.Namespace) -> int:
    layer = _layer(args)
    decision = layer.filesystem.check(args.path, layer.policy.project_root)
    payload = decision.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        verdict_word = "ALLOWED" if decision.allowed else "REFUSED"
        print(verdict_word + ": " + decision.reason)
        if decision.resolved:
            print("resolved: " + decision.resolved)
        if decision.sensitive:
            print("sensitive: " + decision.sensitive)
    return 0 if decision.allowed else 1


def _cmd_grade(args: argparse.Namespace) -> int:
    layer = _layer(args)
    grader = ShellGrader(layer.policy, FilesystemPolicy(layer.policy))
    assessment = grader.assess(args.command, cwd=args.cwd)
    if args.json:
        print(json.dumps(assessment.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        print("risk    : " + assessment.risk.upper())
        print("denied  : " + str(assessment.deny))
        if assessment.deny_reason:
            print("reason  : " + assessment.deny_reason)
        for reason in assessment.reasons:
            print("  - " + reason)
        if assessment.segments:
            print("segments: " + " | ".join(assessment.segments))
    return 2 if assessment.deny else 0


def _cmd_scan(args: argparse.Namespace) -> int:
    layer = _layer(args)
    text = args.text
    if text is None and args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    if text is None:
        text = sys.stdin.read()

    findings = scan_untrusted(text, layer.policy)

    if args.json:
        print(json.dumps([f.model_dump(mode="json") for f in findings], indent=2, ensure_ascii=False))
    elif not findings:
        print("no instruction-like content found (the text is still DATA)")
    else:
        print(str(len(findings)) + " finding(s) — this content is DATA, not instructions:")
        for finding in findings:
            print("  [" + finding.category + "] " + finding.excerpt)
    return 1 if findings else 0


def _cmd_assess(args: argparse.Namespace) -> int:
    layer = _layer(args)
    executor = _executor(args, layer)
    call = _call(args)
    spec = executor.registry.get(args.tool).spec if executor.registry.has(args.tool) else None
    verdict = layer.assess(call, spec=spec)

    if args.json:
        print(json.dumps(verdict.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0 if verdict.decision == "allow" else (2 if verdict.decision == "deny" else 3)
    print("decision: " + verdict.decision.upper())
    print("risk    : " + verdict.risk.upper())
    for reason in verdict.reasons:
        print("  - " + reason)
    if verdict.confirmation is not None:
        print()
        print(verdict.confirmation.summary())
    return 0 if verdict.decision == "allow" else (2 if verdict.decision == "deny" else 3)


def _cmd_confirm(args: argparse.Namespace) -> int:
    """The terminal confirmation UI, then the real execution."""
    layer = _layer(args)
    executor = _executor(args, layer)
    call = _call(args)
    spec = executor.registry.get(args.tool).spec
    verdict = layer.assess(call, spec=spec)

    if verdict.decision == "deny":
        print("REFUSED — this call cannot be confirmed:")
        for reason in verdict.reasons:
            print("  - " + reason)
        return 2
    if verdict.decision == "allow":
        print("allowed without confirmation (" + verdict.risk + " risk)")
        result = executor.execute(call)
        print(result.output if result.ok else "FAILED " + result.error.code)
        return 0 if result.ok else 1

    request = verdict.confirmation
    print("-" * 60)
    print(request.summary())
    print("-" * 60)

    if args.choice:
        choice = args.choice
    else:
        answer = input("1) reject  2) once  3) session  [1]: ").strip() or "1"
        choice = CHOICE_LABELS.get(answer, answer)
    if choice not in ("reject", "once", "session"):
        print("unknown choice: " + choice, file=sys.stderr)
        return 2

    decision = layer.decide(call, choice)  # type: ignore[arg-type]
    print("choice: " + choice + " -> " + decision.decision)
    if decision.decision == "deny":
        return 1

    result = executor.execute(call, confirmed=True)
    print(result.output if result.ok else "FAILED " + result.error.code + ": " + result.error.message)
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.safety.cli")
    parser.add_argument("--project", default=None, help="project root (default: cwd)")
    parser.add_argument("--log", default=None, help="tool call log path")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-path", help="apply the filesystem policy to one path")
    p.add_argument("--path", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_check_path)

    p = sub.add_parser("grade", help="grade a shell command")
    p.add_argument("--command", required=True)
    p.add_argument("--cwd", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_grade)

    p = sub.add_parser("scan", help="look for instruction-like content in untrusted text")
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("assess", help="show the verdict for one tool call")
    p.add_argument("--tool", required=True)
    p.add_argument("--args", default="{}")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_assess)

    p = sub.add_parser("confirm", help="render the confirmation UI and run the call")
    p.add_argument("--tool", required=True)
    p.add_argument("--args", default="{}")
    p.add_argument("--choice", default=None, choices=["reject", "once", "session"])
    p.set_defaults(func=_cmd_confirm)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
