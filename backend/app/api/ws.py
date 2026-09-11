"""WebSocket endpoint /ws (M0 echo + M8 console protocol).

Two frame families travel on one socket, because the M0 echo contract is
already shipped and the console needs the richer one:

    M0 compatibility  {"type": "message" | "error", ...}
    documented events {"event": "...", "timestamp": ..., "session_id": ...,
                       "payload": {...}}          (docs/api-protocol.md)

Client frames:

    {"type": "chat", "content": "..."}                      echo (M0)
    {"type": "ask", "content": "..."}                      one question -> the real model,
                                                           streamed back as assistant_delta
    {"type": "run", "task": "...", "mode": "single|multi", ...}
    {"type": "stop", "run_id": "..."}
    {"type": "confirm", "request_id": "...", "choice": "reject|once|session"}
    {"type": "snapshot"}                                    recovery snapshot

Every inbound frame is untrusted DATA: it is parsed, validated and only then
acted on. A malformed frame never breaks the connection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..agents.models import AgentEvent
from ..context import SessionManager
from ..deps import get_agent_runtime, get_session_manager
from ..runtime import AgentRuntime
from ..models import (
    ChatInbound,
    ErrorInfo,
    ErrorOutbound,
    MessageOutbound,
    new_message,
)
from ..recovery import build_snapshot
from ..services import ChatService

router = APIRouter()
chat_service = ChatService()

# Which documented event name carries each internal agent event.
EVENT_NAMES = {
    "run_start": "agent_update",
    "step_start": "agent_update",
    "model_request": "agent_update",
    "model_reply": "assistant_delta",
    "parse_failed": "error",
    "tool_start": "tool_call",
    "tool_retry": "agent_update",
    "tool_result": "tool_result",
    "blocked": "error",
    "checkpoint": "state_update",
    "loop_detected": "error",
    "context_pressure": "agent_update",
    "context_rotated": "state_update",
    "model_recovered": "agent_update",
    "confirm_request": "confirm_request",
    # The loop's own end is an agent update: the RUNTIME publishes the single
    # terminal "done" for a run, and two done frames with different payloads
    # would make a client render the end twice.
    "run_end": "agent_update",
    # The runtime's terminal frame and its error frame carry the documented
    # names. Without these two rows a client never sees a run end or fail: every
    # internal event fell through to the default below (found by the M9
    # regression suite, whose WS case waited forever for "done").
    "done": "done",
    "error": "error",
    "assistant_delta": "assistant_delta",
}

# docs/api-protocol.md names the events a client may receive.
DOCUMENTED_EVENTS = (
    "assistant_delta",
    "tool_call",
    "tool_result",
    "state_update",
    "memory_update",
    "agent_update",
    "confirm_request",
    "error",
    "done",
)


def envelope(event: AgentEvent, session_id: str) -> dict:
    """Wrap one agent event in the documented envelope."""
    name = EVENT_NAMES.get(event.type, "agent_update")
    payload: dict = dict(event.data)
    payload.setdefault("type", event.type)
    payload.setdefault("message", event.message)
    payload.setdefault("step", event.step)
    if event.tool:
        payload.setdefault("tool", event.tool)
    if event.ok is not None:
        payload.setdefault("ok", event.ok)
    frame = {
        "event": name,
        "timestamp": event.at.astimezone(timezone.utc).isoformat(),
        "session_id": session_id,
        "payload": payload,
    }
    # docs/api-protocol.md: the correlation ids are optional TOP-LEVEL fields
    # as well, so a client can key on them without digging into the payload.
    call_id = event.data.get("call_id")
    if call_id:
        frame["tool_call_id"] = call_id
    request_id = event.data.get("request_id") or event.data.get("id")
    if event.type == "confirm_request" and request_id:
        frame["request_id"] = request_id
    role = event.data.get("role")
    if role:
        frame["agent_id"] = role
    return frame


async def _send_event(websocket: WebSocket, frame: dict) -> None:
    await websocket.send_json(frame)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    runtime: AgentRuntime = Depends(get_agent_runtime),
    sessions: SessionManager = Depends(get_session_manager),
) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    outbox: asyncio.Queue[dict] = asyncio.Queue()

    def current_session() -> str:
        try:
            return sessions.current_session_id() or ""
        except Exception:  # pragma: no cover - defensive
            return ""

    def on_event(event: AgentEvent) -> None:
        frame = envelope(event, current_session())
        try:
            loop.call_soon_threadsafe(outbox.put_nowait, frame)
        except RuntimeError:  # pragma: no cover - the loop is gone
            pass

    unsubscribe = runtime.subscribe(on_event)

    await websocket.send_json(
        MessageOutbound(
            message=new_message("assistant", "Connected. Send a message to echo it.")
        ).model_dump(mode="json")
    )

    async def pump() -> None:
        """Push runtime events to the socket as they happen."""
        while True:
            frame = await outbox.get()
            await websocket.send_json(frame)

    sender = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive_json()
            if not isinstance(raw, dict):
                await websocket.send_json(
                    ErrorOutbound(
                        error=ErrorInfo(
                            code="invalid_frame",
                            message="Frame must be a JSON object.",
                        )
                    ).model_dump(mode="json")
                )
                continue

            kind = raw.get("type")

            if kind == "chat":
                try:
                    inbound = ChatInbound.model_validate(raw)
                except ValidationError as exc:
                    await websocket.send_json(
                        ErrorOutbound(
                            error=ErrorInfo(
                                code="invalid_frame",
                                message=f"Unsupported frame: {exc.error_count()} validation error(s).",
                            )
                        ).model_dump(mode="json")
                    )
                    continue
                await websocket.send_json(
                    MessageOutbound(message=chat_service.handle(inbound)).model_dump(mode="json")
                )
                continue

            if kind == "ask":
                try:
                    record = runtime.ask(str(raw.get("content", "")))
                except (RuntimeError, ValueError) as exc:
                    await websocket.send_json(
                        ErrorOutbound(
                            error=ErrorInfo(code="ask_rejected", message=str(exc))
                        ).model_dump(mode="json")
                    )
                    continue
                await websocket.send_json(
                    {
                        "event": "agent_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": current_session(),
                        "payload": {
                            "status": "asking",
                            "run_id": record.run_id,
                            "question": record.task[:400],
                        },
                    }
                )
                continue

            if kind == "run":
                try:
                    record = runtime.start(
                        str(raw.get("task", "")),
                        mode=str(raw.get("mode", "single")),
                        max_steps=raw.get("max_steps"),
                        max_rounds=raw.get("max_rounds"),
                        auto_confirm=bool(raw.get("auto_confirm", False)),
                    )
                except (RuntimeError, ValueError) as exc:
                    await websocket.send_json(
                        ErrorOutbound(
                            error=ErrorInfo(code="run_rejected", message=str(exc))
                        ).model_dump(mode="json")
                    )
                    continue
                await websocket.send_json(
                    {
                        "event": "agent_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": current_session(),
                        "payload": {"status": "started", "run_id": record.run_id, "task": record.task},
                    }
                )
                continue

            if kind == "stop":
                stopped = runtime.stop(raw.get("run_id"))
                await websocket.send_json(
                    {
                        "event": "agent_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": current_session(),
                        "payload": {"status": "stop_requested", "stopped": stopped},
                    }
                )
                continue

            if kind == "confirm":
                choice = str(raw.get("choice", ""))
                request_id = str(raw.get("request_id", ""))
                accepted = runtime.confirm(request_id, choice)
                if not accepted:
                    await websocket.send_json(
                        ErrorOutbound(
                            error=ErrorInfo(
                                code="no_pending_confirmation",
                                message="No confirmation is waiting with id " + request_id,
                            )
                        ).model_dump(mode="json")
                    )
                    continue
                await websocket.send_json(
                    {
                        "event": "agent_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": current_session(),
                        "payload": {"status": "confirmed", "choice": choice},
                    }
                )
                continue

            if kind == "snapshot":
                snapshot = build_snapshot(sessions=sessions)
                await websocket.send_json(
                    {
                        "event": "state_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": current_session(),
                        "payload": {"snapshot": snapshot.model_dump(mode="json")},
                    }
                )
                continue

            await websocket.send_json(
                ErrorOutbound(
                    error=ErrorInfo(
                        code="invalid_frame",
                        message="Unsupported frame type: " + str(kind),
                    )
                ).model_dump(mode="json")
            )
    except WebSocketDisconnect:
        return
    finally:
        unsubscribe()
        sender.cancel()
        try:
            await sender
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
