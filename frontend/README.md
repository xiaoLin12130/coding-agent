# Frontend (M0)

React 18 + TypeScript + Vite + Tailwind three-column console:
Sessions | Chat | Workbench.

## Run

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5273, proxies /api and /ws to 127.0.0.1:8000
```

Start the backend first (`cd backend && python -m uvicorn app.main:app --port 8000`).

The dev server binds `127.0.0.1:5273` (dedicated port, `strictPort`), because
port 5173 is already used by another project on this machine.

## Verify

```bash
npm run typecheck
npm test
npm run build
```

## WebSocket contract

```jsonc
// client -> server
{"type": "chat", "content": "hello"}

// server -> client
{"type": "message", "message": {"id": "...", "role": "assistant", "content": "Echo: hello", "created_at": "..."}}
{"type": "error",   "error":   {"code": "invalid_frame", "message": "..."}}
```

Set `VITE_WS_URL` to override the derived `ws(s)://<host>/ws` URL.

## M0 scope

Implemented: connection handling with bounded backoff reconnect, chat
send/render, echo display, Project State panel read from
`GET /api/project_state` + `GET /api/memory`.

Placeholders (later milestones): provider/settings, tool calls, memory
entries, file diffs, agent logs.
