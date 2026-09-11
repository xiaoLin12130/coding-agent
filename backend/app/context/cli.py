"""Context / State command line (M2).

    cd backend
    python -m app.context.cli sessions
    python -m app.context.cli transcript [--session ID] [--limit 20]
    python -m app.context.cli context --task "finish M2"
    python -m app.context.cli memory                 # list stored memory
    python -m app.context.cli propose --key k --value v
    python -m app.context.cli rotate [--reason manual]
    python -m app.context.cli resume                 # what a restart would see

Everything is local: no model, no browser, no network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..storage import StateStore
from .builder import ContextBuilder
from .memory import MemoryStore
from .models import ContextBudget, MemoryProposal
from .session import SessionManager


def _manager(args: argparse.Namespace) -> SessionManager:
    root = Path(args.sessions_dir) if args.sessions_dir else None
    return SessionManager(root, keep_turns_on_rotation=args.keep_turns)


def _print(payload: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


# --- commands -------------------------------------------------------------


def _cmd_sessions(args: argparse.Namespace) -> int:
    manager = _manager(args)
    snapshot = manager.start()
    rows = [
        {
            "id": info.id,
            "archived": info.archived,
            "messages": info.message_count,
            "turns": info.turn_count,
            "title": info.title,
        }
        for info in manager.sessions()
    ]
    if args.json:
        _print({"active_session_id": snapshot.active_session_id, "sessions": rows}, True)
        return 0
    print(f"active: {snapshot.active_session_id} (recovered={snapshot.recovered})")
    for row in rows:
        mark = "archived" if row["archived"] else "active  "
        print(f"  [{mark}] {row['id']}  messages={row['messages']} turns={row['turns']}")
    return 0


def _cmd_transcript(args: argparse.Namespace) -> int:
    manager = _manager(args)
    session_id = args.session or manager.start().active_session_id
    entries = manager.transcript_of(session_id or "")
    if args.json:
        _print([e.model_dump(mode="json") for e in entries[-args.limit :]], True)
        return 0
    print(f"session {session_id}: {len(entries)} message(s)")
    for entry in entries[-args.limit :]:
        tool = f" ({entry.tool_name})" if entry.tool_name else ""
        print(f"  [{entry.index}] {entry.role}{tool}: {entry.one_line(100)}")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    manager = _manager(args)
    builder = ContextBuilder(
        manager.transcript,
        manager.memory,
        manager.store,
        budget=ContextBudget(max_chars=args.budget, min_section_chars=args.min_section),
        recent_turns=args.recent_turns,
    )
    session_id = args.session or manager.start().active_session_id or ""
    context = builder.build(
        session_id=session_id,
        system=args.system,
        task=args.task,
        memory_query=args.memory_query,
    )
    if args.json:
        _print(context.model_dump(mode="json"), True)
        return 0
    print(f"session {session_id} | budget {context.budget_chars} | used {context.total_chars}")
    for section in context.sections:
        flag = " (truncated)" if section.truncated else ""
        print(
            f"  {section.priority}. {section.name:15} {section.included_chars:6} chars{flag}"
        )
        if args.show:
            print("     " + section.content.replace("\n", "\n     ")[: args.show])
    if context.dropped_sections:
        print(f"  dropped: {', '.join(context.dropped_sections)}")
    if args.render:
        print("\n--- rendered ---")
        print(context.render())
    return 0


def _cmd_memory(args: argparse.Namespace) -> int:
    store = MemoryStore(StateStore())
    if args.query:
        entries = store.search(args.query)
    else:
        entries = store.all()
    if args.json:
        _print([e.model_dump(mode="json") for e in entries], True)
        return 0
    print(f"{len(entries)} memory entr{'y' if len(entries) == 1 else 'ies'}")
    for entry in entries:
        print(f"  {entry.namespace}/{entry.key}: {entry.value}")
    return 0


def _cmd_propose(args: argparse.Namespace) -> int:
    store = MemoryStore(StateStore())
    decision = store.propose(
        MemoryProposal(
            key=args.key,
            value=args.value,
            namespace=args.namespace,
            reason=args.reason,
            proposed_by="cli",
        )
    )
    if args.json:
        _print(decision.model_dump(mode="json"), True)
    else:
        print(f"{decision.decision}: {decision.reason}")
    return 0 if decision.decision in ("accepted", "updated") else 2


def _cmd_resume(args: argparse.Namespace) -> int:
    """What a freshly started program sees (the M2 acceptance path)."""
    manager = _manager(args)
    snapshot = manager.start()
    state = manager.store.load_project_state()
    builder = ContextBuilder(manager.transcript, manager.memory, manager.store)
    context = builder.build(
        session_id=snapshot.active_session_id,
        system="You are a helpful software engineer assistant.",
        task=state.current_task or "",
    )
    payload = {
        "session": {
            "id": snapshot.active_session_id,
            "recovered": snapshot.recovered,
            "message_count": snapshot.message_count,
            "turn_count": snapshot.turn_count,
        },
        "project_state": state.model_dump(mode="json"),
        "memory_count": manager.memory.count(),
        "context": {
            "sections": [s.name for s in context.sections],
            "dropped": context.dropped_sections,
            "total_chars": context.total_chars,
            "budget_chars": context.budget_chars,
        },
    }
    if args.json:
        _print(payload, True)
        return 0
    session = payload["session"]
    print(f"session   : {session['id']} (recovered={session['recovered']})")
    print(f"messages  : {session['message_count']} across {session['turn_count']} turn(s)")
    print(f"milestone : {state.current_milestone} | task: {state.current_task}")
    print(f"memory    : {payload['memory_count']} entry(ies)")
    print(f"context   : {context.total_chars}/{context.budget_chars} chars")
    print(f"  sections: {', '.join(payload['context']['sections']) or '(none)'}")
    if context.dropped_sections:
        print(f"  dropped : {', '.join(context.dropped_sections)}")
    return 0


def _cmd_rotate(args: argparse.Namespace) -> int:
    manager = _manager(args)
    manager.start()
    builder = ContextBuilder(manager.transcript, manager.memory, manager.store)
    before = builder.build(
        session_id=manager.current_session_id() or "", system="", task=""
    )
    rotation = manager.rotate(reason=args.reason)
    after = builder.build(
        session_id=manager.current_session_id() or "", system="", task=""
    )
    if args.json:
        payload = rotation.model_dump(mode="json")
        payload["context_before_chars"] = before.total_chars
        payload["context_after_chars"] = after.total_chars
        _print(payload, True)
        return 0
    print(f"archived {rotation.archived_session_id} -> {rotation.new_session_id}")
    print(f"reason   : {rotation.reason}")
    print(
        f"summarised {rotation.summary.summarized_count} message(s), "
        f"carried {len(rotation.carried_entry_indices)} verbatim"
    )
    print(f"context  : {before.total_chars} -> {after.total_chars} chars")
    if after.total_chars >= before.total_chars:
        # Not a failure: the seed is a fixed cost, so rotating a session that
        # is nowhere near the budget cannot reclaim anything.
        print(
            "note     : this session was far below the budget, so the seed cost "
            "more than it reclaimed. Rotation pays off only near the limit "
            "(gate it with SessionManager.should_rotate)."
        )
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sessions-dir", default=None, help="override the sessions directory")
    parser.add_argument("--keep-turns", type=int, default=3, help="turns kept verbatim on rotation")
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.context.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sessions", help="list sessions and the active one")
    _add_common(p)
    p.set_defaults(func=_cmd_sessions)

    p = sub.add_parser("transcript", help="show a session transcript")
    _add_common(p)
    p.add_argument("--session", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=_cmd_transcript)

    p = sub.add_parser("context", help="preview the context for one turn")
    _add_common(p)
    p.add_argument("--session", default=None)
    p.add_argument("--task", default="", help="the current task")
    p.add_argument("--system", default="You are a helpful software engineer assistant.")
    p.add_argument("--memory-query", default=None)
    p.add_argument("--budget", type=int, default=28_000)
    p.add_argument("--min-section", type=int, default=200)
    p.add_argument("--recent-turns", type=int, default=3)
    p.add_argument("--show", type=int, default=0, help="also print N chars of each section")
    p.add_argument("--render", action="store_true", help="print the assembled context")
    p.set_defaults(func=_cmd_context)

    p = sub.add_parser("memory", help="list or search stored memory")
    _add_common(p)
    p.add_argument("--query", default=None)
    p.set_defaults(func=_cmd_memory)

    p = sub.add_parser("propose", help="run one memory proposal through the review pipeline")
    _add_common(p)
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--namespace", default="user")
    p.add_argument("--reason", default="cli")
    p.set_defaults(func=_cmd_propose)

    p = sub.add_parser("resume", help="show what a restart recovers")
    _add_common(p)
    p.set_defaults(func=_cmd_resume)

    p = sub.add_parser("rotate", help="archive the active session and continue in a new one")
    _add_common(p)
    p.add_argument("--reason", default="manual")
    p.set_defaults(func=_cmd_rotate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
