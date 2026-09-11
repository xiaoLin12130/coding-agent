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
---

# Context / State layer (M2)

`app/context/` keeps the four kinds of data apart, per `docs/state-context.md`:

| Module | Responsibility |
| --- | --- |
| `transcript.py` | `TranscriptStore` — immutable session history, one append-only JSONL per session |
| `memory.py` | `MemoryStore` — long-lived knowledge, writable only through the `memory_propose` review pipeline |
| `builder.py` | `ContextBuilder` — assembles exactly what one turn sends, under a budget |
| `session.py` | `SessionManager` — sessions that survive a restart, plus rotation |
| `models.py` | Pydantic models for all of the above |
| `cli.py` | manual entry points |

Not part of M2: Tool layer, SafetyLayer, Executor, AgentLoop (M3/M4).

## Context rules

Priority order, highest first:

```text
system > task > project_state > memory > recent transcript > tool result > history summary
```

* Budget is measured in **characters** (`ContextBudget`, default 28 000) because M2 has no
  tokenizer behind the provider boundary.
* Sections are admitted in priority order; what does not fit is **truncated** (head + tail,
  the omission size is recorded, and a `reference` points at the full text), and the
  lowest-priority sections are **dropped** outright.
* `system` and `task` are never dropped.
* Tool output, page text and file text are wrapped in an explicit
  `<<<UNTRUSTED_DATA>>>` marker: they are DATA, never instructions.
* An empty project state renders as nothing, so an unstarted project does not inject
  placeholder lines into every turn.

## Memory

The model may only propose. `MemoryStore.propose()` runs the full pipeline:

```text
filter -> deduplicate -> conflict detection -> sensitive check -> write
```

* An equal value is a `duplicate`; the same key with a different value is a `conflict`
  (resolve it with an explicit `update()`).
* Anything resembling a credential (private key block, `sk-…`/`ghp_…`/`AKIA…` token,
  `password = …`, bearer token, JWT) is rejected before it can be persisted.
* A fully rejected batch never rewrites `memory.json`.

## Sessions

Everything needed to resume lives on disk (`state/sessions/index.json` plus one JSONL
transcript per session), so a restart continues instead of starting over. A corrupt index
is rebuilt from the transcripts; a torn final line only loses that last line.

When the context approaches the hard threshold the caller gates on
`should_rotate()` and then calls `rotate()`, which:

```text
save Project State -> summarise the old transcript -> archive the session
-> open a new session seeded with Project State + memory + current task
   + the last N turns verbatim
```

The seed summary is **bounded** (`seed_summary_chars`, default 1500) — embedding the whole
summary would rebuild a context as large as the one rotation exists to escape. Rotation
only reclaims space when the session is actually near the budget; the seed is a fixed
cost, so rotating early can grow the context. The CLI says so when that happens.

## CLI

```bash
cd backend

python -m app.context.cli sessions
python -m app.context.cli transcript --limit 20
python -m app.context.cli context --task "finish M2" --render
python -m app.context.cli memory --query stack
python -m app.context.cli propose --key k --value v     # exit 2 when rejected
python -m app.context.cli resume                        # what a restart recovers
python -m app.context.cli rotate --reason manual
```

## REST (read-only)

| Path | Purpose |
| --- | --- |
| `GET /api/sessions` | active session id plus every session |
| `GET /api/sessions/{id}` | one session's metadata and transcript |
| `GET /api/messages?session_id=&limit=` | transcript entries (newest `limit`) |
| `GET /api/context?task=` | preview of the next turn's assembled context |

Nothing in M2 writes state through the API, and no endpoint executes anything.
