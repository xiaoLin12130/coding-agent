"""WebSocket endpoint /ws.

M0 contract:

    client -> {"type": "chat", "content": "..."}
    server -> {"type": "message", "message": {...}}
    server -> {"type": "error", "error": {"code": "...", "message": "..."}}

Every inbound frame is untrusted DATA: it is parsed, validated and only then
answered. A malformed frame never breaks the connection.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..models import (
    ChatInbound,
    ErrorInfo,
    ErrorOutbound,
    MessageOutbound,
    new_message,
)
from ..services import ChatService

router = APIRouter()
chat_service = ChatService()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        MessageOutbound(
            message=new_message("assistant", "Connected. Send a message to echo it.")
        ).model_dump(mode="json")
    )

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
            reply = chat_service.handle(inbound)
            await websocket.send_json(
                MessageOutbound(message=reply).model_dump(mode="json")
            )
    except WebSocketDisconnect:
        return
