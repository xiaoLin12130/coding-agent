"""Pydantic models for the browser layer.

These are the single source of truth for provider profiles, completion
signals, on-disk artifacts and captured replies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReplySource = Literal["network", "clipboard", "dom"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompletionPolicy(BaseModel):
    """Multi-signal completion detection policy.

    Completion requires all configured signals to agree:

    * the stop/generating control is gone,
    * the captured text stopped changing for 'stable_polls' consecutive polls,
    * the captured text is not empty.

    'timeout_ms' is the mandated fallback: on timeout the caller receives
    whatever was captured so far together with timed_out=True.
    """

    model_config = ConfigDict(extra="forbid")

    timeout_ms: int = Field(default=120_000, gt=0)
    start_timeout_ms: int = Field(default=15_000, gt=0)
    poll_interval_ms: int = Field(default=250, gt=0)
    stable_polls: int = Field(default=3, ge=1)
    min_wait_ms: int = Field(default=300, ge=0)


class ProviderProfile(BaseModel):
    """Declarative description of one web chat page.

    The provider implementation is generic; a profile is data describing a
    specific site (URL + selectors + optional network capture), so selector
    details never leak into provider or agent code.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    url: str
    verified: bool = False
    notes: str = ""

    ready_selector: str | None = None
    input_selector: str
    send_button_selector: str | None = None
    send_key: str = "Enter"
    stop_button_selector: str | None = None
    assistant_message_selector: str
    copy_button_selector: str | None = None
    copy_status_selector: str | None = None
    login_required_selector: str | None = None
    login_indicator_selector: str | None = None

    network_response_patterns: list[str] = Field(default_factory=list)
    network_text_path: str = "delta"
    network_content_types: list[str] = Field(
        default_factory=lambda: ["text/event-stream", "application/json"]
    )

    completion: CompletionPolicy = Field(default_factory=CompletionPolicy)

    @field_validator("url")
    @classmethod
    def _url_has_scheme(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("url must be absolute, e.g. https://host/path")
        return value


class CompletionTimeline(BaseModel):
    """What the completion detector observed, for debugging and tests."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    finished_at: datetime
    duration_ms: int
    completed: bool
    timed_out: bool
    generation_started: bool
    polls: int
    stable_polls: int
    stop_button_seen: bool
    text_length: int
    signals: list[str] = Field(default_factory=list)
    note: str = ""


class DomSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    captured_at: datetime
    html_path: str | None = None
    text_path: str | None = None
    html_bytes: int = 0
    text_chars: int = 0


class BrowserArtifacts(BaseModel):
    """Files written for one browser run (screenshots, DOM snapshot, logs)."""

    model_config = ConfigDict(extra="forbid")

    run_dir: str
    screenshots: list[str] = Field(default_factory=list)
    dom_snapshots: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)

    def all_paths(self) -> list[str]:
        return [*self.screenshots, *self.dom_snapshots, *self.logs]


class CapturedText(BaseModel):
    """Raw reply text plus the channel it was captured from."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: ReplySource
    network_urls: list[str] = Field(default_factory=list)


class ProviderReply(BaseModel):
    """One captured assistant reply.

    'text' is untrusted page content: DATA, never an instruction.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    source: ReplySource
    completed: bool
    timed_out: bool
    duration_ms: int
    timeline: CompletionTimeline
    artifacts: BrowserArtifacts
    network_urls: list[str] = Field(default_factory=list)


class CapturedResponse(BaseModel):
    """Bookkeeping for one network response observed on the page."""

    model_config = ConfigDict(extra="forbid")

    url: str
    status: int
    content_type: str
    finished: bool = False
    body: str | None = None
    error: str | None = None


def path_str(path: Path | None) -> str | None:
    return None if path is None else str(path)


def as_json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
