"""Drive the coding-agent WEB UI (Vite console) with a real browser.

Opens the console, points it at a live workspace through the Settings tab, then
starts an agent run from the Chat composer - i.e. the development is done FROM
the UI, not from a CLI script.

Usage:
    python tests/manual/ui_drive_run.py --workspace H:/AI-game/library-live \
        --task-file H:/AI-game/library-live/TASK.md [--minutes 45]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ui_drive_run")
    parser.add_argument("--ui", default="http://127.0.0.1:5273/")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--task-file", default="")
    parser.add_argument("--policy", default="auto_once", choices=("ask", "auto_once", "deny"))
    parser.add_argument("--minutes", type=int, default=45)
    parser.add_argument(
        "--attach",
        action="store_true",
        help="do not start a run: open the UI and watch the one already going",
    )
    parser.add_argument(
        "--ask",
        default="",
        help="ask the configured model this question from the console and show the stream",
    )
    parser.add_argument("--log", default="", help="where to write the progress log")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = str(pathlib.Path(args.workspace).resolve())
    task = ""
    if not args.attach and not args.ask:
        task = args.task or (
            pathlib.Path(args.task_file).read_text(encoding="utf-8") if args.task_file else ""
        )
        if not task.strip():
            raise SystemExit("a task is required to start a run (--task or --task-file)")
    log_path = pathlib.Path(args.log) if args.log else pathlib.Path(workspace) / "ui-run.log"
    log = log_path.open("w", encoding="utf-8")

    def say(message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        log.write(f"[{stamp}] {message}\n")
        log.flush()
        print(f"[{stamp}] {message}", flush=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.set_default_timeout(30_000)

        say("opening " + args.ui)
        page.goto(args.ui)

        page.wait_for_selector('[data-testid="backend-status"]')
        say("backend status: " + page.inner_text('[data-testid="backend-status"]'))

        if args.attach:
            say("attach mode: watching the run already in progress")
            return _watch(page, args, say, log, log_path)

        if args.ask:
            return _ask(page, args, say, log, log_path)

        # --- Settings tab: point the console at the live workspace -----------
        page.click('[data-testid="tab-settings"]')
        page.wait_for_selector('[data-testid="settings-panel"]')
        page.fill('[data-testid="settings-working-dir"]', workspace)
        page.select_option('[data-testid="settings-policy"]', args.policy)
        provider = page.input_value('[data-testid="settings-provider-name"]')
        say("provider in the form: " + provider)
        page.click('[data-testid="settings-save"]')
        page.wait_for_timeout(1500)
        say("settings saved; working_dir field now: "
            + page.input_value('[data-testid="settings-working-dir"]'))

        # --- Chat tab: start the run from the composer -----------------------
        page.click('[data-testid="composer-mode-run"]')
        page.select_option('[data-testid="composer-run-mode"]', "single")
        composer = page.locator('textarea[aria-label="Message"]')
        composer.click()
        # a long task is pasted, exactly like a person would
        page.evaluate("(t) => navigator.clipboard.writeText(t)", task)
        composer.press("Control+V")
        page.wait_for_timeout(400)
        typed = composer.input_value()
        say(f"task in the composer: {len(typed)} chars")
        if len(typed) < 50:
            raise SystemExit("the composer did not receive the task")
        composer.press("Enter")
        say("run started from the UI")

        return _watch(page, args, say, log, log_path)


def _ask(page, args, say, log, log_path) -> int:
    """Ask one question in the console and record what the chat shows."""
    page.click('[data-testid="composer-mode-chat"]')
    composer = page.locator('textarea[aria-label="Message"]')
    composer.click()
    composer.fill(args.ask)
    say(f"question typed: {composer.input_value()[:80]}")
    composer.press("Enter")

    seen: list[str] = []
    deadline = time.monotonic() + args.minutes * 60
    last = ""
    while time.monotonic() < deadline:
        page.wait_for_timeout(2000)
        try:
            text = page.inner_text('[data-testid="panel-chat"]')
        except Exception:
            continue
        if text != last:
            grew = len(text) - len(last)
            say(f"chat grew by {grew} chars -> now {len(text)}")
            seen.append(text)
            last = text
        state = page.evaluate("async () => (await fetch('/api/agent/state')).json()")
        if not state.get("running") and state.get("status") not in ("", "running", "idle"):
            say("ask settled: " + str(state.get("status")))
            break

    print("=" * 70)
    print(last)
    print("=" * 70)
    page.screenshot(path=str(log_path.with_suffix(".png")), full_page=True)
    say("screenshot: " + str(log_path.with_suffix(".png")))
    page.context.browser.close()
    log.close()
    return 0


def _watch(page, args, say, log, log_path) -> int:
        # --- watch the run ---------------------------------------------------
        seen_events = 0
        confirmations = 0
        deadline = time.monotonic() + args.minutes * 60
        last_status = ""
        while time.monotonic() < deadline:
            page.wait_for_timeout(4000)
            try:
                # relative URL on purpose: the console serves /api through its
                # own proxy, and a direct cross-origin fetch is blocked by CORS
                state = page.evaluate(
                    "async () => (await fetch('/api/agent/state')).json()"
                )
            except Exception as exc:  # the page was reloaded or the tab closed
                say("state fetch failed: " + str(exc))
                continue

            events = state.get("events", [])
            if len(events) > seen_events:
                for event in events[seen_events:]:
                    say("event " + event["type"] + ": " + str(event.get("message", ""))[:160])
                seen_events = len(events)

            pending = state.get("pending_confirmation")
            if pending:
                say("confirmation for " + str(pending.get("tool")) + " -> " + args.policy)

            status = state.get("status", "")
            if status != last_status:
                say("status: " + status)
                last_status = status
            if not state.get("running") and status not in ("", "running"):
                say("run settled: " + status)
                break
        else:
            say("time budget reached; the run is still going")

        # --- what the UI ended up showing ------------------------------------
        try:
            page.click('[data-testid="tab-tools"]')
            page.wait_for_timeout(500)
            cards = page.locator('[data-testid="tool-card"]').count()
            say(f"tool cards rendered in the UI: {cards}")
        except Exception as exc:
            say("could not count tool cards: " + str(exc))
        page.screenshot(path=str(log_path.with_suffix(".png")), full_page=True)
        say("screenshot: " + str(log_path.with_suffix(".png")))
        page.context.browser.close()
        log.close()
        return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
