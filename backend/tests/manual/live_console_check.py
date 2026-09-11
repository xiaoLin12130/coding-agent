"""Live console check: a real uvicorn process, a real browser WebSocket.

Not collected by pytest (the filename is not test_*.py): it binds ports and
starts a browser, so it is a manual/CI-optional check rather than a unit test.

    cd backend
    ../.venv/Scripts/python.exe tests/manual/live_console_check.py

It verifies two things the offline suite cannot:

* the console selects its provider from the settings document - here the
  OFFLINE scripted provider, so no web LLM and no login are involved
* a run reaches a real client over the documented WebSocket envelope, ending
  with the terminal 'done' frame (a real M8 defect: neither 'done' nor 'error'
  was ever delivered, and the test that covered it hung instead of failing)

Exit code 0 means every assertion held.
"""
import json, os, pathlib, subprocess, sys, tempfile, time, urllib.request

root = pathlib.Path(tempfile.mkdtemp(prefix="m9live-")) / "project"
(root / "src").mkdir(parents=True)
(root / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

plan = root / "plan.json"
plan.write_text(json.dumps([
    json.dumps({"name": "read_file", "arguments": {"path": "src/calc.py"}}),
    "Read it: add() subtracts today.",
]), encoding="utf-8")

state = root / "state"
state.mkdir()
(state / "settings.json").write_text(json.dumps({
    "working_dir": str(root),
    "provider": {"adapter": "scripted", "options": {"plan": str(plan)}},
}), encoding="utf-8")

env = dict(os.environ)
env.update({
    "CODING_AGENT_PROJECT_ROOT": str(root),
    "CODING_AGENT_STATE_DIR": str(state),
    "CODING_AGENT_RUNS_DIR": str(root / "runs"),
    "CODING_AGENT_SESSIONS_DIR": str(state / "sessions"),
    "CODING_AGENT_CHECKPOINTS_DIR": str(state / "checkpoints"),
})

port = 8123
log_path = root.parent / "server.log"
log_file = open(log_path, "w", encoding="utf-8")
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
    env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True,
)
try:
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:" + str(port) + "/api/health", timeout=1) as reply:
                if reply.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("the server never became healthy")

    with urllib.request.urlopen("http://127.0.0.1:" + str(port) + "/api/settings") as reply:
        settings = json.loads(reply.read().decode("utf-8"))
    print("adapter served by /api/settings:", settings["provider"]["adapter"])
    print("catalog:", [item["name"] for item in settings["provider"]["available"]])

    import http.server, threading, functools

    page_dir = root.parent / "page"
    page_dir.mkdir(exist_ok=True)
    (page_dir / "index.html").write_text("<!doctype html><title>ws probe</title>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(page_dir))
    static = http.server.ThreadingHTTPServer(("127.0.0.1", 8124), handler)
    threading.Thread(target=static.serve_forever, daemon=True).start()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto("http://127.0.0.1:8124/")
        result = page.evaluate(
            """(port) => new Promise((resolve) => {
                const frames = [];
                const ws = new WebSocket('ws://127.0.0.1:' + port + '/ws');
                const timer = setTimeout(() => resolve({frames, timedOut: true}), 25000);
                ws.onmessage = (event) => {
                    const frame = JSON.parse(event.data);
                    const name = frame.event || frame.type;
                    frames.push(name);
                    if (name === 'done') { clearTimeout(timer); resolve({frames, timedOut: false, last: frame}); }
                };
                ws.onerror = (event) => { clearTimeout(timer); resolve({frames, error: String(event && event.type)}); };
                ws.onclose = (event) => { if (frames.length === 0) { clearTimeout(timer); resolve({frames, closed: event.code + ' ' + event.reason}); } };
                ws.onopen = () => ws.send(JSON.stringify({type: 'run', task: 'read src/calc.py', mode: 'single'}));
            })""",
            port,
        )
        browser.close()

    print("result:", json.dumps(result)[:400])
    frames = result["frames"]
    print("frames:", frames)
    if not frames:
        print("--- server log ---")
        log_file.flush()
        print(log_path.read_text(encoding="utf-8", errors="replace")[-2500:])
    print("done frame:", json.dumps(result.get("last", {}))[:200])
    assert not result["timedOut"], "no done frame arrived"
    assert "tool_call" in frames and "tool_result" in frames
    assert frames[-1] == "done", frames[-1]
    print("LIVE CHECK: PASS")
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except Exception:
        server.kill()