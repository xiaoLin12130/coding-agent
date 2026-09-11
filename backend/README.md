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
---

# Tool layer (M3)

`app/tools/` implements the pipeline `ToolCall -> Parser -> Executor -> Tool Result`.

| Module | Responsibility |
| --- | --- |
| `parser.py` | `ToolCallParser` — JSON, JSON5, code fences, multiple calls, bracket matching, structured errors |
| `json5.py` | hand-written JSON5 subset reader (no dependency) |
| `registry.py` | `ToolRegistry` — names, JSON schemas, risk levels |
| `builtin.py` | the nine tools |
| `executor.py` | `Executor` — the single real entry point |
| `cli.py` | manual entry points |

## Tools

| Tool | Risk | Notes |
| --- | --- | --- |
| `list_dir` | low | idempotent; skips `.git`, `node_modules`, `.venv`, `dist`, `runs` |
| `read_file` | low | idempotent; line ranges; rejects non-UTF-8 and files over 512 kB |
| `write_file` | medium | idempotent; reports created vs updated and how much was replaced |
| `apply_patch` | medium | exact-fragment replacement; refuses an ambiguous anchor and writes nothing on failure |
| `search` | low | idempotent; regex + glob filter, bounded results |
| `run_shell` | high | **requires confirmation**; bounded timeout and output |
| `memory_propose` | medium | goes through the M2 review pipeline; a rejected proposal is a failed call |
| `update_project_state` | medium | idempotent; partial update, appends without duplicating |
| `ask_user` | low | needs a user channel; fails cleanly when there is none |

## Parser

Accepted packaging for one call: a bare object, an array, a `tool_calls`
wrapper, an OpenAI-style `function` block, a fenced block (`json`/`json5`), or
any of those embedded in prose. Argument keys may be `arguments`,
`parameters`, `args`, `input`, and may arrive as a JSON string.

Failures are **structured**, never free text: each carries a stable `code`,
the character offset when one exists, and a `repair_hint`. Codes:
`empty_input`, `no_tool_call`, `invalid_json`, `unbalanced_brackets`,
`not_an_object`, `missing_name`, `missing_arguments`, `invalid_arguments`,
`unknown_tool`, `too_many_calls`.

`ParseRetryPolicy(max_attempts=3)` tracks the bounded retry budget and turns
the latest failure into an instruction for the model (`repair_prompt`).

## Executor

The single real entry point. It provides what `docs/safety.md` requires of it:

* **schema validation** — arguments are validated against the tool's Pydantic
  model, and **unknown parameters are rejected** rather than ignored
* **error handling** — nothing propagates: every failure becomes a
  `ToolResult` with a structured `error` (including unexpected exceptions)
* **logging** — every call, including replays, is appended to
  `runs/tool-calls.jsonl`; a broken log path never breaks an execution
* **idempotency** — an identical call to an idempotent tool is replayed from
  cache and marked `idempotent_replay`

### Confirmation (now enforced by M4)

Tools declare `risk` and `requires_confirmation`; the Executor refuses to run
a confirmation-requiring tool unless a confirmation or an approval hook is
present. M4 turned this seam into a real policy — see the Safety layer section
below.

## CLI

```bash
cd backend

python -m app.tools.cli list
python -m app.tools.cli schema read_file
python -m app.tools.cli parse --text "{name: 'read_file', args: {path: 'x'}}"
python -m app.tools.cli run read_file --args '{"path": "README.md"}'
python -m app.tools.cli run run_shell --args '{"command": "echo hi"}' --confirm
```

The CLI goes through the same Executor as the model will; it bypasses nothing.
---

# Safety layer (M4)

`app/safety/` is the gate every tool call passes through:

```text
ToolCall -> Validation -> SafetyLayer -> Confirmation -> Executor -> Tool
```

| Module | Responsibility |
| --- | --- |
| `policy.py` | every rule in one place: roots, sensitive files, shell grading, injection patterns |
| `paths.py` | filesystem policy — nothing outside the project, no secrets |
| `shell.py` | shell risk grading (LOW / MEDIUM / HIGH, deny-by-default) |
| `injection.py` | untrusted content is DATA; only model/user output may issue calls |
| `layer.py` | `SafetyLayer` — allow / confirm / deny, session grants, output flags |
| `cli.py` | the terminal confirmation UI |

## What is enforced

**1. File scope.** Every path argument is resolved (symlinks followed) and must
land inside the project root — or an explicitly configured extra root. A
sibling directory sharing a prefix (`project-evil` vs `project`) does not
pass. Extra roots are allowed; sensitive names are not, even inside the project:
`.env`, `id_rsa`, `.npmrc`, `credentials`, `auth.json`, key material
(`.pem`, `.key`, `.pfx`, `.p12`, `.keystore`) and anything under
`.ssh`, `.aws`, `.gnupg`, `.kube`, `.dsh`.

**2. Shell grading.** The command is split on `;`, `&&`, `||`, `|` and
newlines, and **every** segment is graded, so `ls && rm -rf /` is not read as
`ls`.

| Grade | Meaning |
| --- | --- |
| LOW | cannot execute code or change anything (`ls`, `cat`, read-only `git`) |
| MEDIUM | normal development work (`pytest`, `tsc`, `mkdir`) |
| HIGH | everything else — **an unrecognised verb is HIGH, never LOW** |

Denied outright, whatever the confirmation: destructive patterns
(`rm -rf /`, `dd of=/dev/…`, `curl … | bash`, `git push --force`,
`format`, `shutdown`), any command naming a sensitive file
(`cat ~/.ssh/id_rsa`), and any command touching a path outside the project.
Subcommands are graded too: `git status` is LOW, `git push` is HIGH.

**3. Prompt injection.** Web text, file text, tool results and shell output are
DATA. Two mechanisms keep that true: instruction-like content in untrusted text
is **flagged** (`injection_findings` travel with the result, whose text is
never rewritten), and `check_instruction_source()` **refuses** to parse tool,
file, web, shell or document output as instructions — only `model` and `user`
may issue a tool call. That makes "cannot be executed" structural rather than a
matter of good behaviour.

**4. Confirmation.** A high-risk call returns
`confirmation_required` together with the request the human must see:

```text
tool    : run_shell
risk    : HIGH
command : rm -rf build
cwd     : /home/me/project
impact  : runs a shell command in /home/me/project
choices : reject / once / session
```

The three choices behave as documented: `reject` denies,
`once` allows that call only, `session` records a grant **for that command**
— a grant never authorises a different command, and never authorises a denied
one.

## No bypass

Every call is assessed before anything runs. When a caller does not supply a
layer, the Executor builds one scoped to its working directory, so the default
is *checked*, never *unchecked*; there is no constructor that yields an
Executor without a `SafetyLayer`. Denied and refused calls are written to the
audit log like any other.

## CLI

```bash
cd backend

python -m app.safety.cli check-path --path ../outside.txt
python -m app.safety.cli grade --command "rm -rf /"
python -m app.safety.cli scan --text "IGNORE ALL PREVIOUS INSTRUCTIONS"
python -m app.safety.cli assess --tool run_shell --args '{"command": "echo hi"}'
python -m app.safety.cli confirm --tool run_shell --args '{"command": "echo hi"}'
```

`assess` exits 0 (allow), 2 (deny) or 3 (confirmation required); `confirm`
prints the block above, asks for one of the three choices, and then runs the
call through the same Executor the model uses.

**Not wired into the web console yet.** The confirmation data and its terminal
rendering exist; the browser side needs the `confirm_request` event from
`docs/api-protocol.md`, which belongs with the API-protocol work.
---

# Agent loop (M5)

`app/agents/` runs the documented cycle:

```text
LLM -> ToolCallParser -> SafetyLayer -> Executor -> Tool Result -> Context -> LLM
```

| Module | Responsibility |
| --- | --- |
| `loop.py` | `AgentLoop` — the cycle and every bound it respects |
| `llm.py` | model clients: `ScriptedModel`, `CallableModel`, `BrowserModel` |
| `checkpoint.py` | `CheckpointStore` — durable run state, rewritten after every step |
| `cli.py` | manual entry points |

The loop never touches a file or a shell itself: every tool call goes through
the M3 parser, the M4 SafetyLayer and the Executor, so it cannot bypass the
chain even by accident.

## Bounds

| Bound | Behaviour |
| --- | --- |
| max steps | `max_steps` (default 25) ends the run with status `max_steps` |
| timeout | a wall-clock budget ends it with `timeout` |
| user interrupt | a `should_stop` callback is checked before every step → `interrupted` |
| tool retry | only failures the Executor marks `retryable` are retried (a timeout, not a missing file) |
| parse retry | unparsable output is re-asked with the M3 repair prompt, bounded |
| loop detection | a repeating call pattern (including `A,B,A,B,…`) ends it with `loop` |
| checkpoint | written after every step, so a crash leaves a resumable run |
| confirmation | a hook answers `reject`/`once`/`session` before a risky call runs |

## Context and history

Each step rebuilds the context with the M2 builder (system, task, project
state, memory, recent transcript, tool results, history summary). Tool results
are also written to the session transcript with the `tool` role, so the model
still sees earlier results two turns later — the context alone only carries the
previous step's output.

Tool output is DATA. It is wrapped in the untrusted marker and scanned for
instruction-like content; only `model` and `user` output may be parsed as
instructions.

## Statuses

`completed` · `max_steps` · `timeout` · `interrupted` · `blocked` (the model
stopped after the SafetyLayer refused) · `loop` · `error`

## CLI

```bash
cd backend

cat > plan.json <<'JSON'
{"replies": ["{\"name\": \"read_file\", \"arguments\": {\"path\": \"a.txt\"}}", "done"]}
JSON

python -m app.agents.cli run --task "read a.txt" --script plan.json --confirm once
python -m app.agents.cli checkpoints
python -m app.agents.cli resume --run-id <id>
```

`--script` supplies canned model replies so the loop can be exercised without
a web LLM; every tool call still goes through parser, SafetyLayer and Executor.

## Not in M5

Multi-agent orchestration (Planner/Coder/Reviewer/…): `docs/runtime-agents.md`
requires the single loop to be solid first. Session recovery across a context
threshold, browser/login recovery and crash recovery are M6; M5 supplies the
checkpoint they build on.
---

# Recovery layer (M6)

`app/recovery/` continues a task after something broke.

| Module | Failure it handles |
| --- | --- |
| `thresholds.py` | the context filling up (soft / hard ratios) |
| `session_recovery.py` | the documented Context-full sequence, with the injections verified |
| `run_recovery.py` | the program restarted (checkpoint → continue) |
| `browser_recovery.py` | the browser crashed, or the login expired |
| `snapshot.py` | a WebSocket client reconnected and needs to re-sync |
| `cli.py` | manual entry points |

## Context thresholds

Ratios of the builder's budget (`ContextThresholds`: soft 0.7, hard 0.9), so
the policy follows the budget rather than duplicating a character count.

* **soft** — keep the session and carry fewer recent turns
* **hard** — run the documented sequence:

```text
finish the turn -> save Project State -> summarise the transcript
-> archive the session -> open a seeded one -> continue the task
```

The new session is seeded with **Project State + Memory + the last turns
verbatim + the current task**, and `SessionRecovery` **verifies** each of those
landed (a rotation that silently lost the task would otherwise look fine).
An empty rotation is not reported as a failure.

The AgentLoop evaluates the pressure at every step boundary, so a long task
rots into a fresh session instead of overflowing.

## Browser and login recovery

`BrowserRecovery` wraps a session factory:

* a dead page (the driver raises) is **restarted** — bounded by `max_restarts`
* an expired login triggers `recover_session`, which waits for a **manual**
  sign-in (credentials, captcha and risk control are never automated)
* `call(fn)` recovers once and retries, never in an endless loop

Because a restart produces a **new provider**, `BrowserModel` accepts
`provider_factory=...` so the model follows the restarted page instead of
talking to the dead one.

## Restart and reconnect

* `RunRecovery` finds the latest unfinished run (`plan`, `pending`) and
  continues it with a freshly built loop. A real model is stateless, so a caller
  supplying a fresh one sets `restore_model_state=False` lest the checkpoint
  rewind it past its first reply.
* `build_snapshot` is everything a reconnecting client needs. The server keeps
  **no essential state in memory** — sessions, transcripts, memory and
  checkpoints are all on disk, so a reconnect re-reads the facts.

## REST (read-only)

| Path | Purpose |
| --- | --- |
| `GET /api/recovery` | what a reconnect or restart would find |
| `GET /api/recovery/runs` | runs that did not finish |
| `GET /api/recovery/runs/{id}` | one run's recovery plan |
| `GET /api/recovery/pressure` | how full the next turn's context would be |

## CLI

```bash
cd backend

python -m app.recovery.cli status --task "finish M6"
python -m app.recovery.cli pressure --task "finish M6"
python -m app.recovery.cli runs
python -m app.recovery.cli resume --run-id <id> --script plan.json
python -m app.recovery.cli rotate --reason context_budget
python -m app.recovery.cli browser --profile mock
```

## Not in M6

Multi-agent orchestration (Planner/Coder/Reviewer/…) is M7.
---

# Runtime multi-agent (M7)

`app/agents/roles.py` and `app/agents/orchestrator.py` run the collaboration
`docs/runtime-agents.md` describes:

```text
Planner -> Coder -> Reviewer -> 修复?
                                 |- yes -> Coder
                                 '- no  -> done
```

with StateKeeper, MemoryCurator and SafetyGuard as supporting roles.

## The six roles

| Role | Job | Tools it may use |
| --- | --- | --- |
| Planner | understand the goal, split the work | `list_dir`, `read_file`, `search` |
| Coder | implement, then run the tests | the above + `write_file`, `apply_patch`, `run_shell` |
| Reviewer | verify code, tests and completion | `list_dir`, `read_file`, `search`, `run_shell` |
| MemoryCurator | judge long-lived knowledge | `memory_propose` |
| StateKeeper | record where the project stands | read tools + `update_project_state` |
| SafetyGuard | check the plan for overreach | read tools only |

**Boundaries are enforced by capability, not by instruction.** Each role is
handed a registry containing only its allowed tools, so a Planner has no write
tool registered at all: a prompt can be ignored, an absent tool cannot be
called. A typo in a role's allowlist fails loudly instead of silently widening
it.

## The four hard constraints

| Constraint | How it holds |
| --- | --- |
| no role bypasses the Executor | every role runs through an `AgentLoop`, so through the M4 SafetyLayer and the Executor; the roles themselves never touch a file, a shell or a tool |
| no role writes shared state directly | Project State and Memory change only through `update_project_state` / `memory_propose`, which keep their validation and review |
| no infinite loop | `max_rounds` on the collaboration, `max_steps` per role, a wall-clock budget, and the per-run loop guard |
| no infinite agent conversation | repeating the same verdict **and** the same issues stalls the collaboration (`stall_threshold`) instead of spinning |

## Verdicts

The Reviewer and the SafetyGuard answer in a fixed shape:

```text
VERDICT: APPROVED | NEEDS_FIX      (reviewer)
VERDICT: SAFE | BLOCKED            (safety guard)
ISSUE: <one concrete problem>      (repeatable)
NOTES: <one line>
```

An answer **without** a verdict is `unknown`, which is treated as a fix request
for the Reviewer (assuming approval from unparseable text is how a broken
review passes) and as "not blocked" for the SafetyGuard. A BLOCKED plan stops
the collaboration before the Coder runs.

## Routing roles to models

`AgentOrchestrator(model_factory=...)` builds a model per role, so a deployment
can put a stronger model behind the Reviewer. Tests use it to script each role
separately.

## Result

`OrchestrationResult` carries the plan, every round's verdict and issues, every
role run (status, tool names, duration), the collaboration's event stream and
the tool totals. Every role's tool calls go to the same audit log
(`runs/tool-calls.jsonl`) as a single-agent run, confirmations included.

## CLI

```bash
cd backend

python -m app.agents.cli roles
python -m app.agents.cli orchestrate --task "fix add()" --script plan.json --confirm once
```

`--script` is either `{"replies": [...]}` shared by every role, or a per-role
mapping `{"planner": [...], "coder": [...], ...}` — multi-call roles need the
latter to stay deterministic.

## Not in M7

The web console (M8). `docs/runtime-agents.md` keeps all real execution behind
the Executor, which the orchestrator respects: it holds no tools of its own.
---

# Console backend (M8)

The Workbench needs three things the CLI cannot give it, and M8 adds exactly
those: sessions and state it can read and change, a run it can watch live, and
a confirmation a human can answer.

| Module | Responsibility |
| --- | --- |
| `runtime.py` | `AgentRuntime` — one console-facing run: worker thread, event ring, stop button, confirmation queue |
| `console_model.py` | the model the console drives: the real browser provider, wrapped in the M6 recovery |
| `settings.py` | the settings document (provider, browser, working dir, safety, confirmation, thresholds, multi-agent) |
| `api/console.py` | sessions, settings, logs, agents, observability, run control |
| `api/ws.py` | the WebSocket protocol (M0 echo + the documented event envelope) |

## The run is observable, stoppable and answerable

* **observable** — the run happens on a worker thread and publishes
  `AgentEvent`s; the WebSocket streams them and `GET /api/agent/state` replays
  them, so a client that connects late still sees the whole run
* **stoppable** — `POST /api/agent/stop` (or the `stop` frame) sets the flag
  the agent loop already checks before every step
* **answerable** — a high-risk call publishes a `confirm_request` and the
  worker waits; `POST /api/agent/confirm` (or the `confirm` frame) answers it.
  An unanswered prompt expires and is treated as a rejection, so a run can
  never hang on a closed browser tab
* **one at a time** — a second run is refused with 409, because the event ring,
  the confirmation queue and the stop flag describe exactly one run

## Confirmation policy

| Policy | Behaviour |
| --- | --- |
| `ask` | every high-risk call waits for a human (default) |
| `auto_once` | the runtime answers "once" itself (unattended runs) |
| `deny` | the runtime always rejects |

`once` is accepted as an alias for `auto_once` and normalised, so either
spelling reads back as the canonical one.

## Tool cards need correlation

`tool_start` carries `call_id`, `tool`, `arguments` and `risk`;
`tool_result` carries the same `call_id` plus `ok`, `error_code`, `risk`,
`duration_ms` and `summary`. Ids are unique **for the whole run**
(`<run>-<step>-<index>`), not per parse: with one call per step every id would
otherwise be `call-1` and every card would collapse into one.

## WebSocket

Two families travel on one socket, because the M0 echo contract is already
shipped:

```jsonc
// M0
{"type": "chat", "content": "hello"}
{"type": "message", "message": {...}}

// console
{"type": "run",  "task": "...", "mode": "single"|"multi"}
{"type": "stop", "run_id": "..."}
{"type": "confirm", "request_id": "...", "choice": "reject"|"once"|"session"}
{"type": "snapshot"}
```

Server events use the documented envelope
(`docs/api-protocol.md`): `{event, timestamp, session_id, payload}` plus the
optional correlation ids (`request_id`, `tool_call_id`, `agent_id`) at the top
level, so a client can key on them without digging into the payload.

## REST added in M8

| Path | Purpose |
| --- | --- |
| `POST /api/sessions` / `POST /api/sessions/{id}/archive` | new and archived sessions |
| `GET/PUT /api/settings` | the settings document |
| `GET /api/logs` | the tool audit trail and the current run's events |
| `GET /api/agents`, `GET /api/agent/state` | roles, running run, history |
| `POST /api/agent/run` / `stop` / `confirm` | run control |
| `GET /api/observability/artifacts` / `file` | screenshots, DOM snapshots and logs (`file` is restricted to the runs directory) |

## Boundaries that did not move

The console executes nothing directly. Every run goes through the same
`AgentLoop`/`AgentOrchestrator`, so the M4 SafetyLayer and the Executor apply
unchanged; a run's tool calls land in the same `runs/tool-calls.jsonl` audit
log as the CLI's. The console cannot widen a role's tools either: the roles in
`/api/settings` are read-only and always come from the code.

---

# Provider adapters (M9)

How the agent reaches a model is an adapter behind a registry, so a new provider
never touches `app/agents`:

| Module | Responsibility |
| --- | --- |
| `app/providers/models.py` | `ProviderInfo` / `ProviderOption`: what a provider is, and what it needs |
| `app/providers/registry.py` | `ProviderRegistry`, `default_registry()`, `build_model()` |
| `app/providers/browser.py` | the shipped default: a web LLM through Playwright (M1 + M6 recovery) |
| `app/providers/scripted.py` | offline replay of a plan file (tests, evaluation, CLI) |
| `app/providers/openai_compatible.py` | any `/chat/completions` endpoint over HTTP |

```bash
cd backend
python -m app.providers.cli list
python -m app.providers.cli show openai_compatible
python -m app.providers.cli check scripted --option plan=plan.json --prompt "hi"
```

Choosing a provider is a settings change, not a code change:

```jsonc
{
  "provider": {
    "adapter": "openai_compatible",   // browser | scripted | openai_compatible
    "model": "qwen2.5-coder",
    "options": {"base_url": "http://127.0.0.1:8080/v1"}
  }
}
```

* `adapter` picks the registry entry; `name` stays the browser profile.
* A **secret** option (an API key) is read from the environment
  (`api_key_env`, default `OPENAI_API_KEY`) and is stripped before the settings
  document is written.
* The registry rejects an unknown option name instead of ignoring it, so a typo
  is reported before a run starts. One document holds the options of every
  adapter; the inactive ones are simply not passed to the active provider.
* `provider.available` in `GET /api/settings` is the read-only catalog, derived
  from the registry like the role list is derived from the code.
* Saving a different provider drops the console's cached model, so the next run
  uses what the page now shows.

Adding one is an adapter plus one registration:

```python
from app.providers import ProviderInfo, register_provider

INFO = ProviderInfo(name="my-model", kind="api", label="My model")

@register_provider(INFO)
def create(**options):
    return MyModelClient(**options)
```

---

# Evaluation (M9)

`app/evaluation/` replays the golden sets through the **real** components —
parser, SafetyLayer, Executor, AgentLoop, SessionManager — and turns the result
into a pass/fail gate.

| Module | Responsibility |
| --- | --- |
| `models.py` | cases, expectations, results, reports, thresholds |
| `dataset.py` | loaders for the two golden files |
| `parser_eval.py` | the parser golden set (exact match, per category, failure samples) |
| `agent_eval.py` | the six scenarios' runner (throwaway workspace per case) |
| `thresholds.py` | what a run must reach to count as a pass |
| `report.py` | markdown + JSON report |
| `runner.py` / `cli.py` | one call / one command to run everything |

```bash
cd backend
python -m app.evaluation.cli run                       # both suites, writes runs/evaluation/<stamp>/
python -m app.evaluation.cli run --suite parser --json
python -m app.evaluation.cli run --out reports/m9      # exit 1 when a threshold fails
```

The data lives in `backend/evaluation/`: `parser_golden.jsonl` (50 cases over
the eight categories docs/testing.md requires, plus a ninth for invented tool
names) and `agent_cases.json` (15 scenarios over the six dimensions
milestones/M9.md requires). A case carries its input **and its contract**; the
harness reports the difference, never the other way round.

| Dimension | What the cases prove |
| --- | --- |
| tool_selection | the tools the task needs, and no write for a read-only question |
| tool_parsing | fences, JSON5 and prose-wrapped calls still execute |
| task_completion | the result on disk is correct, proven by running the project's own check |
| recovery | a failing model end is retried; a run stopped at the step limit resumes |
| safety | a denied call, an outside path, a sensitive file and an unconfirmed command change nothing |
| context_switching | the hard threshold rotates and continues, the soft one compacts |

A case may record a **documented limitation** (`known_gap`): the expectation
still describes today's behaviour, and the report lists the gap so it stays
visible. The three recorded gaps:

* a truncated second call after a complete one is dropped **without any issue**,
  so the model is never told that only one of its two calls ran;
* a call quoted as an **example** in prose is executed like a real one;
* identical calls are returned twice (de-duplication is the loop's job, and the
  loop only stops a repeat after the third identical step).

Thresholds default to 100% of both suites plus coverage checks (categories,
dimensions and case counts), so the regression gate in
`tests/test_evaluation_regression.py` fails the moment a case stops matching —
including the case of a known gap that got fixed, which must then be corrected
in the dataset.

The M9 regression suite also found a real M8 defect: the WebSocket mapping had
no entry for the runtime's `done` and `error` events, so every run ended as an
`agent_update` and no client could ever see a run finish or fail. The test that
covered it waited forever for a frame that could not arrive. Both names are
mapped now (`app/api/ws.py`) and guarded by tests.
