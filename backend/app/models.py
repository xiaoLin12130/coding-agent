"""Pydantic models.

M0 models two things:

* the persisted state files (project_state.json / memory.json)
* the WebSocket message protocol used by /ws

Both are the single source of truth for their shapes; API and services
only ever exchange these models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["user", "assistant"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Persisted state
# --------------------------------------------------------------------------


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: str
    status: str = "pending"


class ProjectState(BaseModel):
    """Factual state of the project being worked on."""

    model_config = ConfigDict(extra="allow")

    current_milestone: str | None = None
    current_task: str | None = None
    goal: str | None = None
    todos: list[TodoItem] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests: list[Any] = Field(default_factory=list)
    failures: list[Any] = Field(default_factory=list)
    decisions: list[Any] = Field(default_factory=list)
    checkpoint: Any | None = None
    commands_run: list[Any] = Field(default_factory=list)
    git_branch: str | None = None
    cwd: str | None = None


class MemoryEntry(BaseModel):
    """One long-lived memory item.

    Timestamps stay strings so an existing memory.json keeps its exact
    formatting when it is loaded and written back (M2 decision).
    """

    model_config = ConfigDict(extra="allow")

    key: str
    value: str
    namespace: str = "user"
    source: str = ""
    sensitive: bool = False
    source_turn: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Memory(BaseModel):
    """Long-lived, reusable knowledge."""

    model_config = ConfigDict(extra="allow")

    memories: list[MemoryEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------
# WebSocket protocol (fixed contract, shared with the frontend)
# --------------------------------------------------------------------------


class ChatMessage(BaseModel):
    id: str
    role: Role
    content: str
    created_at: datetime


class ErrorInfo(BaseModel):
    code: str
    message: str


class ChatInbound(BaseModel):
    """Client -> server frame: {"type": "chat", "content": "..."}"""

    model_config = ConfigDict(extra="ignore")

    type: Literal["chat"]
    content: str

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value


class MessageOutbound(BaseModel):
    """Server -> client frame carrying one chat message."""

    type: Literal["message"] = "message"
    message: ChatMessage


class ErrorOutbound(BaseModel):
    """Server -> client frame carrying a protocol error."""

    type: Literal["error"] = "error"
    error: ErrorInfo


def new_message(role: Role, content: str) -> ChatMessage:
    return ChatMessage(
        id=f"{role}-{int(utc_now().timestamp() * 1000)}",
        role=role,
        content=content,
        created_at=utc_now(),
    )
