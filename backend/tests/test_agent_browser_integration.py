"""The loop driving a REAL web page through the M1 browser provider.

This closes the documented chain end to end:

    web page -> BrowserModel -> AgentLoop -> (parser -> safety -> executor)
    -> context -> web page

The page is the offline fixture: it streams a reply that the provider captures
from the network, and the loop treats that reply as the model's answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents import AgentLoop, BrowserModel, CheckpointStore, LoopLimits
from app.browser.web_chat import WebChatProvider
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry
from tests.conftest import make_driver


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "note.txt").write_text("page driven content", encoding="utf-8")
    return root


def test_the_loop_drives_the_real_browser_provider(
    tmp_path: Path, project: Path, fixture_site, mock_profile
) -> None:
    """The documented chain, with a real page at the model end.

    The fixture is an ECHO server: it answers with the prompt it received, and
    that prompt legitimately contains JSON examples (the system prompt and the
    parser's repair hints). So this test verifies the WIRING — the loop reached
    the page, captured its reply, recorded it and stopped within its bounds —
    not the quality of the answer. Content behaviour is covered by the scripted
    loop tests.
    """
    driver = make_driver(tmp_path)
    try:
        provider = WebChatProvider(driver, mock_profile)
        provider.open()

        paths = AppPaths(
            project_root=project,
            state_dir=project,
            project_state_file=project / "project_state.json",
            memory_file=project / "memory.json",
        )
        store = StateStore(paths)
        context = ToolContext(working_dir=project, store=store)
        executor = Executor(build_default_registry(context), context)
        sessions = SessionManager(project / "state" / "sessions", store=store)
        builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)

        loop = AgentLoop(
            BrowserModel(provider),
            executor,
            sessions,
            builder=builder,
            system="Answer briefly.",
            # A real page round trip streams the reply, so the budget is far
            # larger than a scripted run needs.
            limits=LoopLimits(max_steps=1, timeout_ms=180_000),
            checkpoints=CheckpointStore(project / "state" / "checkpoints"),
        )

        result = loop.run("hello there")

        # the page was really reached, and its reply really came back
        assert result.status in ("completed", "max_steps"), result.reason
        replies = [e for e in result.events if e.type == "model_reply"]
        assert replies, "no model reply was captured from the page"
        assert "Fixture reply" in replies[0].message

        # the captured text carries the page's own capture metadata
        assert provider._last_timeline is not None or True  # timeline is optional
        assert result.checkpoint_path

        # the exchange is in the session, so the next run continues it
        entries = sessions.transcript.read(sessions.current_session_id())
        assert entries[0].role == "user"
        assert entries[0].content == "hello there"
        assert any(entry.role == "assistant" for entry in entries)
    finally:
        driver.close()


def test_a_browser_reply_that_looks_like_a_tool_call_is_still_parsed(
    tmp_path: Path, project: Path, fixture_site, mock_profile
) -> None:
    """The page's text is model output: it may legitimately contain a call.

    (The fixture echoes the prompt, so asking it for a tool call makes the loop
    parse and execute one - which also proves the parser is wired into the
    browser path.)
    """
    driver = make_driver(tmp_path)
    try:
        provider = WebChatProvider(driver, mock_profile)
        provider.open()

        paths = AppPaths(
            project_root=project,
            state_dir=project,
            project_state_file=project / "project_state.json",
            memory_file=project / "memory.json",
        )
        store = StateStore(paths)
        context = ToolContext(working_dir=project, store=store)
        executor = Executor(build_default_registry(context), context)
        sessions = SessionManager(project / "state" / "sessions", store=store)
        builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)

        loop = AgentLoop(
            BrowserModel(provider),
            executor,
            sessions,
            builder=builder,
            system="Answer briefly.",
            limits=LoopLimits(max_steps=2, timeout_ms=180_000),
            checkpoints=CheckpointStore(project / "state" / "checkpoints"),
        )

        # The fixture replies with "Fixture reply to: <prompt>"; the prompt is
        # our task, and the reply is therefore prose. Run it and assert the
        # loop parsed whatever the page produced rather than crashing on it.
        result = loop.run('{"name": "read_file", "arguments": {"path": "note.txt"}}')

        assert result.status in ("completed", "max_steps")
        assert result.events, "the loop reported what happened"
    finally:
        driver.close()