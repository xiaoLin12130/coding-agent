# Frontend — Workbench console (M8)

React 18 + TypeScript + Vite 5 + Tailwind 3 + Zustand, built as the complete
console described in `milestones/M8.md` and `docs/frontend.md`:

```
┌────────────┬──────────────────────┬─────────────────────────┐
│ Sessions   │ Chat                 │ Workbench               │
│ new/search │ Markdown + code      │ State Tools Memory Files│
│ switch     │ streaming, copy      │ Terminal Logs Agents    │
│ archive    │ diff, retry, edit    │ Observe (replay)        │
│ provider   │ stop, Tool Cards     │ Settings                │
└────────────┴──────────────────────┴─────────────────────────┘
```

## Run

```bash
npm install
npm run gen:api   # regenerate src/api/schema.d.ts from the backend OpenAPI
npm run dev       # http://127.0.0.1:5273, proxies /api and /ws to 127.0.0.1:8000
```

The dev server binds `127.0.0.1:5273` (`strictPort`); port 5173 belongs to
another project on this machine. Start the backend first
(`cd ../backend && python -m uvicorn app.main:app --port 8000`).

## Types are generated, never hand-written

`docs/api-protocol.md` forbids two hand-maintained definitions of one backend
model, so every backend type in the console comes from
`src/api/schema.d.ts`, which `scripts/gen-api-types.mjs` generates from
`components.schemas` of the backend OpenAPI document:

* `npm run gen:api` fetches `http://127.0.0.1:8000/openapi.json`
  (`--url`/API_OPENAPI_URL override) and merges it over the committed frozen
  snapshot, so a running backend can add or correct models but never drop one.
* `npm run gen:api -- --offline` regenerates from
  `scripts/openapi.snapshot.json` alone (this is what keeps the build working
  while the backend is down).
* `npm run gen:api -- --refresh-snapshot` rewrites the snapshot from a live
  backend.
* The generated file is committed, so `npm run build` works offline.

UI-only shapes (timeline messages, tool-call records, replay state) live in
`src/types/ui.ts`; they are not backend models.

## Contract coverage

REST (all through `src/api/client.ts`): health, project_state, memory,
sessions (list/create/detail/archive), messages, context, recovery,
recovery/runs, settings (GET/PUT), logs, agents, observability/artifacts,
observability/file, agent/run, agent/stop, agent/confirm, agent/state.

WebSocket `/ws` (`src/lib/ws.ts`): both frame families —

* M0 echo: `{"type":"chat"}` → `{"type":"message"|"error"}`
* documented envelope: `assistant_delta`, `tool_call`, `tool_result`,
  `state_update`, `memory_update`, `agent_update`, `confirm_request`,
  `error`, `done`
* client frames: `chat`, `run`, `stop`, `confirm`, `snapshot`

A malformed inbound frame is dropped with a notice and never throws.

`src/lib/events.ts` folds the stream into the timeline (tool_call/tool_result
pair by `call_id`, deltas accumulate into one streaming message). The same pure
reducer powers live rendering and the Observe tab's Replay.

## Behaviour when the backend is offline

Every REST failure is normalised to `ApiError`; transport failures set
`backend: "offline"` and the panels render an explicit "Backend offline" state
with a retry button instead of stale or invented data. A socket disconnect is
tracked separately and reconnects with bounded backoff.

## Verify

```bash
npm install
npx tsc --noEmit    # zero errors
npm test            # vitest + jsdom, fetch and WebSocket are mocked
npm run build       # production bundle
```

Tests never open a socket or a network connection: `src/test/fakeClient.ts`
implements the socket client in memory and `src/test/apiMock.ts` answers the
REST routes.

## Not in the frozen contract (therefore not implemented)

* Memory edit/delete, and any file-content endpoint — the Memory panel is
  read-only and the Files panel only shows diffs the stream actually carried.
* A real PTY: the Terminal panel shows the executor's commands and their output
  summaries from the event stream and `project_state.commands_run`.
