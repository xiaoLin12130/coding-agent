# Backend

FastAPI + WebSocket service (M0) and the Playwright browser layer (M1).

## Run

```bash
cd backend
python -m venv .venv          # or use the repo-level .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium   # once, for M1
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

## Test

```bash
cd backend
python -m pytest            # browser tests launch a headed Chromium
```

## Surface (M0)

| Kind | Path | Purpose |
| --- | --- | --- |
| REST | `GET /api/health` | liveness probe |
| REST | `GET /api/project_state` | read `state/project_state.json` |
| REST | `GET /api/memory` | read `state/memory.json` |
| WS | `/ws` | chat frames are echoed back |

### WebSocket contract

```jsonc
// client -> server
{"type": "chat", "content": "hello"}

// server -> client
{"type": "message", "message": {"id": "...", "role": "assistant", "content": "Echo: hello", "created_at": "..."}}
{"type": "error",   "error":   {"code": "invalid_frame", "message": "..."}}
```

Configuration: `CODING_AGENT_STATE_DIR` overrides the state directory
(default `<repo>/state`), `CODING_AGENT_PROJECT_ROOT` overrides the project root.

---

# Browser layer (M1)

`app/browser/` drives a web chat page with Playwright: headed browser,
persistent profile, page open, input, send, completion detection, reply
capture, screenshots and DOM snapshots.

| Module | Responsibility |
| --- | --- |
| `driver.py` | Playwright lifecycle, persistent context, navigation, screenshot, DOM snapshot, network capture |
| `provider.py` | `ProviderAdapter` contract (open / send / wait_until_complete / capture_response / is_logged_in / recover_session) |
| `web_chat.py` | the single M1 provider: selector-driven web chat page |
| `profiles.py` | provider profiles (JSON, one per site) |
| `artifacts.py` | per-run artifact directory under `runs/` |
| `cli.py` | manual entry points |

Not part of M1: Tool layer, SafetyLayer, Executor, AgentLoop, multi-agent
orchestration, automatic context switching.

## CLI

```bash
cd backend

# offline demo target (no real LLM involved)
python -m fixtures.chat_site.server --port 8765

python -m app.browser.cli profiles
python -m app.browser.cli inspect --profile mock
python -m app.browser.cli ask     --profile mock --prompt "hello"
python -m app.browser.cli login   --profile example-web-llm
```

Every run writes artifacts to `runs/<timestamp>-<profile>/`: screenshot PNG,
DOM snapshot (HTML + rendered text), timeline, captured reply and network log.
Exit code 2 from `ask` means the timeout fallback fired and partial text was
returned.

## Provider profiles

A profile is JSON `{name, url, selectors, network patterns, completion policy}`
in `profiles/`; see `profiles/mock.json`. Point the driver at a real site by
copying `profiles/example-web-llm.json`, filling the selectors from an
`inspect` run and signing in manually with the `login` command. The
persistent profile at `.browser-profile/` keeps that session.

## Completion detection

Multi-signal, per `docs/browser.md`: the stop control disappears, the captured
text stops changing for `stable_polls` consecutive polls and the text is not
empty. A timeout always returns the partial text with `timed_out=true`.

Reply capture priority: network/SSE > copy button > DOM.

## Constraints

The browser is always headed. No captcha bypass, fingerprint spoofing,
multi-account evasion or risk-control workarounds; login is manual by design.
Page content is DATA: it is parsed defensively and never executed.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODING_AGENT_RUNS_DIR` | `<repo>/runs` | artifact output |
| `CODING_AGENT_PROFILES_DIR` | `backend/profiles` | provider profiles |
| `CODING_AGENT_BROWSER_PROFILE_DIR` | `<repo>/.browser-profile` | persistent browser profile |
