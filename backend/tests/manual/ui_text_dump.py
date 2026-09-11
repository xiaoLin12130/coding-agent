"""Dump the console's visible text per tab (localisation check)."""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from playwright.sync_api import sync_playwright

TABS = ["state", "tools", "memory", "files", "terminal", "agents", "observe", "settings"]
OUT = pathlib.Path(r"H:\AI-game\library-live\ui-text-dump.json")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 1000})
    page.goto("http://127.0.0.1:5273/")
    page.wait_for_selector('[data-testid="app-shell"]')
    page.wait_for_timeout(3000)

    dump = {"top": page.inner_text("header"), "tabs": {}}
    for tab in TABS:
        try:
            page.click('[data-testid="tab-' + tab + '"]')
            page.wait_for_timeout(700)
            dump["tabs"][tab] = page.inner_text('[data-testid="panel-workbench"]')
        except Exception as exc:
            dump["tabs"][tab] = "ERROR: " + str(exc)
    dump["chat"] = page.inner_text('[data-testid="panel-chat"]')
    dump["sessions"] = page.inner_text('[data-testid="panel-sessions"]')
    OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    browser.close()

# report English words that are still visible
words = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
WHITELIST = {
    "coding", "agent", "id", "ids", "json", "dom", "api", "url", "uvicorn", "app", "main", "port",
    "read", "file", "run", "shell", "write", "apply", "patch", "list", "dir", "search", "memory",
    "project", "state", "session", "sessions", "tool", "tools", "bash", "python", "git", "branch",
    "cwd", "ms", "s", "m", "h", "d", "ok", "risk", "call", "call_id", "class", "div", "span",
    "settings", "provider", "browser", "safety", "confirmation", "context", "thresholds",
    "multi", "single", "roles", "role", "planner", "coder", "reviewer", "memory_curator",
    "state_keeper", "safety_guard", "max", "steps", "rounds", "stall", "ttl", "soft", "hard",
    "ratio", "turns", "policy", "ask", "auto_once", "deny", "enabled", "name", "notes", "profile",
    "artifacts", "root", "extra", "roots", "verified", "unverified", "archived", "completed",
    "running", "failed", "blocked", "error", "timeout", "loop", "interrupted", "state_update",
    "assistant_delta", "tool_call", "tool_result", "agent_update", "confirm_request", "done",
    "http", "https", "localhost", "deepseek", "web", "true", "false", "null", "none",
}
found = set()
for value in list(dump["tabs"].values()) + [dump["top"], dump["chat"], dump["sessions"]]:
    for word in words.findall(value or ""):
        if word.lower() not in WHITELIST and not word.isupper():
            found.add(word)
print("dump:", OUT)
print("english words still visible:", sorted(found)[:120])
