"""Live agent check against a REAL web LLM: the whole stack, one conversation.

Not collected by pytest (the filename is not test_*.py): it starts a server,
opens a headed browser and sends a real prompt to a real site.

    cd backend
    ../.venv/Scripts/python.exe tests/manual/live_browser_agent_check.py

What it proves, in one run:

* the console selects the BROWSER provider from the settings document
* AgentLoop -> BrowserModel -> WebChatProvider -> chat.deepseek.com really works
* the model's tool call goes through the parser, the SafetyLayer and the
  Executor, and the tool result reaches the real model, which then answers
* the page is driven the way a person drives it, and the WHOLE run happens in
  one conversation: the loop asks twice (the tool call, then the answer) and
  the second question continues the chat the first one opened

The logged-in session comes from the repo's persistent browser profile, so no
credentials are touched. Login, captcha and risk-control flows are never
automated (project rule).

Exit code 0 means every assertion held.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[3]
PROFILE_DIR = REPO / ".browser-profile"
PROFILE_NAME = "deepseek-web"
TASK = (
    "Use the read_file tool to read src/calc.py, then answer in one short "
    "sentence what add does. Do not modify any file."
)
BUDGET_S = 600


def free_port() -> int:
    """Ask the OS for a port nobody is using (a fixed one collides)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


PORT = free_port()
ROOT = pathlib.Path(tempfile.mkdtemp(prefix="live-browser-agent-"))
PROJECT = ROOT / "project"
(PROJECT / "src").mkdir(parents=True)
(PROJECT / "src" / "calc.py").write_text(
    "def add(a, b):" + chr(10) + "    return a - b" + chr(10), encoding="utf-8"
)
STATE = PROJECT / "state"
STATE.mkdir()
(STATE / "settings.json").write_text(
    json.dumps(
        {
            "working_dir": str(PROJECT),
            "provider": {"adapter": "browser", "name": PROFILE_NAME},
            "browser": {
                "profile_dir": str(PROFILE_DIR),
                "artifacts_dir": str(PROJECT / "runs"),
            },
            "confirmation": {"policy": "ask", "ttl_seconds": 120},
        }
    ),
    encoding="utf-8",
)

ENV = dict(os.environ)
ENV.update(
    {
        "CODING_AGENT_PROJECT_ROOT": str(PROJECT),
        "CODING_AGENT_STATE_DIR": str(STATE),
        "CODING_AGENT_RUNS_DIR": str(PROJECT / "runs"),
        "CODING_AGENT_SESSIONS_DIR": str(STATE / "sessions"),
        "CODING_AGENT_CHECKPOINTS_DIR": str(STATE / "checkpoints"),
        "CODING_AGENT_BROWSER_PROFILE_DIR": str(PROFILE_DIR),
    }
)


def api(path: str, payload: dict | None = None):
    url = "http://127.0.0.1:" + str(PORT) + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.code, "body": exc.read().decode("utf-8", "replace")}


log_path = ROOT / "server.log"
log_file = open(log_path, "w", encoding="utf-8")
server = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--log-level",
        "warning",
    ],
    env=ENV,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    text=True,
)

try:
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:" + str(PORT) + "/api/health", timeout=1
            ) as reply:
                if reply.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        log_file.flush()
        print(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        raise SystemExit("the server never became healthy")

    settings = api("/api/settings")
    print("port          :", PORT)
    print("adapter       :", settings["provider"]["adapter"])
    print("browser       :", settings["browser"]["profile_dir"])
    print("reuse         :", "on (the run continues one conversation)")
    assert settings["provider"]["adapter"] == "browser", settings["provider"]

    started = api("/api/agent/run", {"task": TASK, "mode": "single", "max_steps": 4})
    print("run           :", started)
    assert started.get("accepted"), started

    deadline = time.monotonic() + BUDGET_S
    confirmations = 0
    while time.monotonic() < deadline:
        state = api("/api/agent/state")
        pending = state.get("pending_confirmation")
        if pending:
            confirmations += 1
            print("confirmation  :", pending.get("tool"), pending.get("risk"))
            api(
                "/api/agent/confirm",
                {"request_id": pending["request_id"], "choice": "once"},
            )
        if not state.get("running"):
            break
        time.sleep(2)
    else:
        api("/api/agent/stop", {})
        raise SystemExit("the run never settled within " + str(BUDGET_S) + "s")

    state = api("/api/agent/state")
    events = state["events"]
    kinds = [event["type"] for event in events]
    tools = [event for event in events if event["type"] == "tool_result"]
    replies = [event for event in events if event["type"] == "model_reply"]

    print()
    print("status        :", state["status"])
    print("steps         :", max((event["step"] for event in events), default=0))
    print("model replies :", len(replies), "->", [event["step"] for event in replies])
    print("tool results  :", [(event.get("tool"), event.get("ok")) for event in tools])
    print("confirmations :", confirmations)
    print("final message :", (replies[-1]["message"][:300] if replies else "(none)"))
    print("server log    :", log_path)

    assert "tool_start" in kinds, "the real model never called a tool"
    assert state["status"] == "completed", state["status"]
    assert len(replies) >= 2, "the loop should ask the model once per step"
    contents = (PROJECT / "src" / "calc.py").read_text(encoding="utf-8")
    assert "return a - b" in contents, "the read-only task must not modify the file"

    # One conversation: the loop asked the real model twice, and the second
    # question continued the thread the first one opened. The evidence is the
    # page itself - a new chat would show a single answer, a continued one shows
    # both.
    run_dirs = sorted((PROJECT / "runs").glob("*-" + PROFILE_NAME))
    snapshots = sorted(run_dirs[-1].glob("*-dom-*.html")) if run_dirs else []
    assert snapshots, "no DOM snapshot was captured"
    html = snapshots[-1].read_text(encoding="utf-8", errors="replace")
    answers = html.count("ds-assistant-message-main-content")
    print("artifacts     :", run_dirs[-1])
    print("answers on the page at the end:", answers)
    assert answers >= 2, "the second question did not continue the same conversation"
    print()
    print("LIVE BROWSER AGENT CHECK: PASS (one run, one conversation)")
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except Exception:
        server.kill()
    log_file.close()
