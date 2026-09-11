"""M11: asking the model from the console, with the answer streaming in.

The console's chat is not the M0 echo any more: an "ask" goes to the configured
provider (a real web LLM in a deployment, a scripted model here) and the answer
arrives as assistant_delta frames while it is written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedModel
from app.agents.models import ModelReply
from app.context import SessionManager
from app.deps import get_agent_runtime, reset_agent_runtime
from app.main import app
from app.runtime import AgentRuntime
from app.settings import SettingsStore
from app.storage import StateStore


class StreamingModel:
    """A model that reports its answer in pieces, like a page being written."""

    name = "streaming"

    def __init__(self, pieces: list[str]) -> None:
        self.pieces = pieces
        self.questions: list[str] = []

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        self.questions.append(prompt)
        return ModelReply(text="".join(self.pieces), source="model")

    def complete_stream(self, prompt: str, system: str | None = None, on_delta=None) -> ModelReply:
        self.questions.append(prompt)
        for index, piece in enumerate(self.pieces):
            if on_delta is not None:
                on_delta(piece, index == 0)
        return ModelReply(text="".join(self.pieces), source="model")

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:  # pragma: no cover - stateless
        return None


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("CODING_AGENT_STATE_DIR", str(root))
    monkeypatch.setenv("CODING_AGENT_RUNS_DIR", str(root / "runs"))
    monkeypatch.setenv("CODING_AGENT_SESSIONS_DIR", str(root / "state" / "sessions"))
    monkeypatch.setenv("CODING_AGENT_CHECKPOINTS_DIR", str(root / "state" / "checkpoints"))
    settings = SettingsStore(root / "state" / "settings.json")
    current = settings.load()
    current.working_dir = str(root)
    settings.save(current)
    return root


def make_runtime(workspace: Path, model) -> AgentRuntime:
    runtime = AgentRuntime(
        SessionManager(workspace / "state" / "sessions", store=StateStore()),
        SettingsStore(workspace / "state" / "settings.json"),
        model_factory=lambda: model,
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    return runtime


def teardown_runtime(runtime: AgentRuntime) -> None:
    app.dependency_overrides.pop(get_agent_runtime, None)
    runtime.wait(timeout=10)
    reset_agent_runtime()


def deltas(runtime: AgentRuntime) -> list[dict]:
    return [event.data for event in runtime.events() if event.type == "assistant_delta"]


# --- the runtime -----------------------------------------------------------


def test_asking_streams_the_answer_in_pieces(workspace: Path) -> None:
    model = StreamingModel(["The answer ", "arrives ", "in pieces."])
    runtime = make_runtime(workspace, model)
    try:
        record = runtime.ask("what is a library system?")
        assert runtime.wait(timeout=10) is True
    finally:
        teardown_runtime(runtime)

    assert record.mode == "ask"
    assert record.status == "completed"
    pieces = deltas(runtime)
    assert [piece["text"] for piece in pieces] == ["The answer ", "arrives ", "in pieces."]
    assert pieces[0]["reset"] is True and pieces[1]["reset"] is False
    assert model.questions == ["what is a library system?"]

    kinds = [event.type for event in runtime.events()]
    assert kinds[0] == "run_start"
    assert kinds[-1] == "done"
    # a model_reply here would be mapped to assistant_delta as well and the
    # console would show the answer twice
    assert "model_reply" not in kinds, kinds


def test_a_model_that_cannot_stream_still_answers(workspace: Path) -> None:
    """No complete_stream(): one whole-text chunk, not a broken answer."""
    model = ScriptedModel(["the entire answer"])
    runtime = make_runtime(workspace, model)
    try:
        runtime.ask("hi")
        runtime.wait(timeout=10)
    finally:
        teardown_runtime(runtime)

    pieces = deltas(runtime)
    assert [piece["text"] for piece in pieces] == ["the entire answer"]
    assert pieces[0]["reset"] is True
    assert runtime.record().status == "completed"


def test_a_failing_model_reports_an_error_and_a_done(workspace: Path) -> None:
    class Broken(StreamingModel):
        def complete_stream(self, prompt, system=None, on_delta=None):
            raise RuntimeError("the page died")

    runtime = make_runtime(workspace, Broken([]))
    try:
        runtime.ask("hi")
        runtime.wait(timeout=10)
    finally:
        teardown_runtime(runtime)

    kinds = [event.type for event in runtime.events()]
    assert "error" in kinds
    assert kinds[-1] == "done"
    assert runtime.record().status == "error"
    assert "the page died" in runtime.record().reason


def test_an_empty_question_is_refused(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["x"]))
    try:
        with pytest.raises(ValueError):
            runtime.ask("   ")
    finally:
        teardown_runtime(runtime)


def test_a_second_question_while_one_is_going_is_refused(workspace: Path) -> None:
    class Slow(StreamingModel):
        def complete_stream(self, prompt, system=None, on_delta=None):
            import time

            time.sleep(1.0)
            return super().complete_stream(prompt, system, on_delta)

    runtime = make_runtime(workspace, Slow(["slow"]))
    try:
        runtime.ask("first")
        with pytest.raises(RuntimeError):
            runtime.ask("second")
    finally:
        teardown_runtime(runtime)


# --- the wire --------------------------------------------------------------


def test_the_websocket_ask_frame_streams_then_done(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["one ", "two"]))
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                ws.send_json({"type": "ask", "content": "hello model"})
                frames = []
                for _ in range(20):
                    frame = ws.receive_json()
                    frames.append(frame)
                    if frame.get("event") == "done":
                        break
    finally:
        teardown_runtime(runtime)

    names = [frame.get("event") for frame in frames if "event" in frame]
    assert names[0] == "agent_update" and frames[0]["payload"]["status"] == "asking"
    assert "assistant_delta" in names, names
    assert names[-1] == "done"
    text = "".join(
        frame["payload"]["text"] for frame in frames if frame.get("event") == "assistant_delta"
    )
    assert text == "one two"
    assert frames[-1]["payload"]["mode"] == "ask"


def test_the_websocket_refuses_an_empty_question(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["x"]))
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                ws.send_json({"type": "ask", "content": "  "})
                frame = ws.receive_json()
    finally:
        teardown_runtime(runtime)

    assert frame["type"] == "error"
    assert frame["error"]["code"] == "ask_rejected"


def test_the_rest_route_accepts_a_question(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["hi there"]))
    try:
        with TestClient(app) as client:
            started = client.post("/api/agent/ask", json={"content": "hello"})
            assert started.status_code == 200
            body = started.json()
            assert body["accepted"] is True and body["mode"] == "ask"
            runtime.wait(timeout=10)
            state = client.get("/api/agent/state").json()
    finally:
        teardown_runtime(runtime)

    assert state["status"] == "completed"
    assert [event["type"] for event in state["events"]].count("assistant_delta") == 1


def test_the_rest_route_refuses_an_empty_question(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["x"]))
    try:
        with TestClient(app) as client:
            assert client.post("/api/agent/ask", json={"content": ""}).status_code == 422
    finally:
        teardown_runtime(runtime)


def test_the_streaming_event_keeps_its_documented_name(workspace: Path) -> None:
    from app.api.ws import DOCUMENTED_EVENTS, EVENT_NAMES

    assert EVENT_NAMES["assistant_delta"] == "assistant_delta"
    assert "assistant_delta" in DOCUMENTED_EVENTS


def test_the_delta_event_reaches_a_client_as_documented_envelope(workspace: Path) -> None:
    runtime = make_runtime(workspace, StreamingModel(["chunk"]))
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                ws.send_json({"type": "ask", "content": "q"})
                frame = None
                for _ in range(20):
                    candidate = ws.receive_json()
                    if candidate.get("event") == "assistant_delta":
                        frame = candidate
                        break
    finally:
        teardown_runtime(runtime)

    assert frame is not None
    assert set(frame) >= {"event", "timestamp", "session_id", "payload"}
    assert frame["payload"]["text"] == "chunk"
