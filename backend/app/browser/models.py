"""Pydantic models for the browser layer.

These are the single source of truth for provider profiles, completion
signals, on-disk artifacts and captured replies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # How long send() waits for a page that is STILL generating before it gives
    # up. Sending a question into a generating page stops that answer, so the
    # provider waits instead of interrupting; if the page never settles, it
    # raises rather than corrupting the answer in flight.
    idle_timeout_ms: int = Field(default=180_000, gt=0)


class HumanPolicy(BaseModel):
    """How the browser acts on the page: like a person, not like a script.

    Delays are ranges, not fixed values, and they are deliberately short by
    default: this is pacing, not camouflage. Set 'enabled: false' for a page
    where instant input is correct (the offline fixture, a local test page).

    Nothing here disguises the browser: no user-agent rewriting, no fingerprint
    patching, no captcha or risk-control handling (project rule).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # Typing rhythm: a FAST band and a SLOW band, not one flat range. People
    # type in bursts - most characters in well under a tenth of a second, a few
    # much slower - so 'typing_fast_chance' of the characters draw from the fast
    # band and the rest from the slow one.
    typing_min_ms: int = Field(default=18, ge=0, le=2_000)
    typing_fast_max_ms: int = Field(default=55, ge=0, le=2_000)
    typing_slow_min_ms: int = Field(default=95, ge=0, le=2_000)
    typing_max_ms: int = Field(default=190, ge=0, le=2_000)
    typing_fast_chance: float = Field(default=0.72, ge=0, le=1)
    key_pause_chance: float = Field(default=0.08, ge=0, le=1)
    # Text at least this long is PASTED, not typed: a person pastes a long
    # prompt, and a page that receives thousands of synthetic keystrokes
    # re-renders on every one of them.
    paste_threshold_chars: int = Field(default=220, ge=1)
    paste_key: str = "Control+V"
    paste_min_ms: int = Field(default=120, ge=0, le=10_000)
    paste_max_ms: int = Field(default=400, ge=0, le=10_000)
    paste_settle_min_ms: int = Field(default=150, ge=0, le=10_000)
    paste_settle_max_ms: int = Field(default=450, ge=0, le=10_000)
    key_pause_min_ms: int = Field(default=120, ge=0, le=5_000)
    key_pause_max_ms: int = Field(default=420, ge=0, le=5_000)
    pause_characters: list[str] = Field(
        default_factory=lambda: [" ", ",", ".", ";", ":", "\n", "，", "。", "！", "？"]
    )
    # Pointer behaviour.
    mouse_steps: int = Field(default=12, ge=1, le=100)
    mouse_max_ms: int = Field(default=90, ge=0, le=2_000)
    click_hold_ms: int = Field(default=60, ge=0, le=2_000)
    # The pause before typing, between text and Enter, and after a reply.
    think_min_ms: int = Field(default=150, ge=0, le=10_000)
    think_max_ms: int = Field(default=600, ge=0, le=10_000)
    pre_send_min_ms: int = Field(default=120, ge=0, le=10_000)
    pre_send_max_ms: int = Field(default=450, ge=0, le=10_000)
    settle_min_ms: int = Field(default=100, ge=0, le=10_000)
    settle_max_ms: int = Field(default=400, ge=0, le=10_000)
    select_all_key: str = "Control+a"

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> "HumanPolicy":
        for low, high in (
            ("typing_min_ms", "typing_fast_max_ms"),
            ("typing_fast_max_ms", "typing_slow_min_ms"),
            ("typing_slow_min_ms", "typing_max_ms"),
            ("key_pause_min_ms", "key_pause_max_ms"),
            ("paste_min_ms", "paste_max_ms"),
            ("paste_settle_min_ms", "paste_settle_max_ms"),
            ("think_min_ms", "think_max_ms"),
            ("pre_send_min_ms", "pre_send_max_ms"),
            ("settle_min_ms", "settle_max_ms"),
        ):
            if getattr(self, low) > getattr(self, high):
                raise ValueError(low + " must not exceed " + high)
        return self


class PreSendToggle(BaseModel):
    """A page switch that must be ON before a message is sent.

    The first one is a site's thinking/reasoning mode: the project wants the
    model's reasoning, so it is switched on by default rather than left to
    whatever the last human session left behind.

    'active_selector' is the CSS that is present only while the switch is ON;
    when it is empty the toggle is clicked whenever it is visible.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    selector: str
    active_selector: str = ""
    enabled: bool = True
    description: str = ""


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
    # Page chrome inside the answer element that must NOT be part of the reply:
    # a code block's language label and its copy/download buttons are rendered
    # inside the answer, so capturing the element verbatim injected
    # "python / 复制 / 下载" into the model's text (and into tool calls).
    ignore_selectors: list[str] = Field(default_factory=list)
    # The element that wraps a code block on this site. When set, code blocks are
    # captured with textContent so their indentation survives (see
    # BrowserDriver.answer_text).
    code_block_selector: str | None = None

    network_response_patterns: list[str] = Field(default_factory=list)
    network_text_path: str = "delta"
    # URLs whose IN-FLIGHT request means "the page is still generating". This is
    # the page's own truth and it is checked in addition to the text-stability
    # heuristic: a model that is thinking, or a long block that has not been
    # rendered yet, shows no text change while it is still working, and a
    # question sent in that window interrupts the answer (M14).
    generating_patterns: list[str] = Field(default_factory=list)
    network_content_types: list[str] = Field(
        default_factory=lambda: ["text/event-stream", "application/json"]
    )

    # How the page is driven (typing rhythm, pointer movement). M10.
    human: HumanPolicy = Field(default_factory=HumanPolicy)
    # Switches turned ON before a message is sent (a site's thinking mode).
    toggles: list[PreSendToggle] = Field(default_factory=list)
    # Reuse the conversation already open in this browser instead of navigating
    # to the site again, which is what a person does: they continue the thread
    # they are in rather than starting a new one for every question.
    reuse_conversation: bool = True

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
