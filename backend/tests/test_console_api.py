"""Console REST + WebSocket protocol tests (M8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import CallableModel
from app.context import SessionManager
from app.deps import get_agent_runtime, reset_agent_runtime
from app.main import app
from app.runtime import AgentRuntime
from app.settings import SettingsStore
from app.storage import StateStore


def tool(name: str, **arguments) -> str:
    return json.dumps({"name": name, "arguments": arguments})


@pytest.fixture()
def project(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text(
        "def add(a, b):" + chr(10) + "    return a - b" + chr(10), encoding="utf-8"
    )
    monkeypatch.setenv("CODING_AGENT_STATE_DIR", str(root))
    monkeypatch.setenv("CODING_AGENT_RUNS_DIR", str(root / "runs"))
    monkeypatch.setenv("CODING_AGENT_SESSIONS_DIR", str(root / "state" / "sessions"))
    monkeypatch.setenv("CODING_AGENT_CHECKPOINTS_DIR", str(root / "state" / "checkpoints"))
    settings = SettingsStore(root / "state" / "settings.json")
    current = settings.load()
    current.working_dir = str(root)
    current.confirmation.policy = "once"
    settings.save(current)
    return root


@pytest.fixture()
def runtime(project: Path):
    holder = {"n": 0}
    replies = [
        tool("read_file", path="src/calc.py"),
        tool("write_file", path="src/calc.py", content="def add(a, b):" + chr(10) + "    return a + b" + chr(10)),
        "done",
    ]

    def decide(prompt: str, system: str | None) -> str:
        index = holder["n"]
        holder["n"] += 1
        return replies[index] if index < len(replies) else "done"

    created = AgentRuntime(
        SessionManager(project / "state" / "sessions", store=StateStore()),
        SettingsStore(project / "state" / "settings.json"),
        model_factory=lambda: CallableModel(decide),
    )
    app.dependency_overrides[get_agent_runtime] = lambda: created
    yield created
    app.dependency_overrides.pop(get_agent_runtime, None)
    created.wait(timeout=20)
    reset_agent_runtime()


@pytest.fixture()
def client(project: Path, runtime) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --- sessions --------------------------------------------------------------


def test_sessions_list_reports_the_active_session(client: TestClient) -> None:
    body = client.get("/api/sessions").json()

    assert body["active_session_id"]
    assert any(s["id"] == body["active_session_id"] for s in body["sessions"])


def test_a_new_session_becomes_active(client: TestClient) -> None:
    before = client.get("/api/sessions").json()["active_session_id"]

    created = client.post("/api/sessions", params={"title": "console session"})

    assert created.status_code == 200
    body = created.json()
    assert body["created"] is True
    assert body["active_session_id"] != before
    assert client.get("/api/sessions").json()["active_session_id"] == body["active_session_id"]


def test_an_archived_session_is_marked_and_copied(client: TestClient, project: Path) -> None:
    # make two sessions: the older one is not active, so it can be archived
    first = client.get("/api/sessions").json()["active_session_id"]
    client.post("/api/sessions")

    response = client.post(f"/api/sessions/{first}/archive")

    assert response.status_code == 200
    body = response.json()
    assert body["archived"] is True
    listing = client.get("/api/sessions").json()["sessions"]
    archived = next(s for s in listing if s["id"] == first)
    assert archived["archived"] is True
    assert Path(archived["archive_path"]).exists()


def test_archiving_the_active_session_opens_a_continuation(client: TestClient) -> None:
    active = client.get("/api/sessions").json()["active_session_id"]

    body = client.post(f"/api/sessions/{active}/archive").json()

    assert body["archived"] is True
    assert body["continues_as"]
    assert client.get("/api/sessions").json()["active_session_id"] == body["continues_as"]


def test_archiving_an_unknown_session_is_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/archive").status_code == 404


def test_messages_are_returned_for_a_session(client: TestClient) -> None:
    session_id = client.get("/api/sessions").json()["active_session_id"]

    body = client.get("/api/messages", params={"session_id": session_id}).json()

    assert body["session_id"] == session_id
    assert isinstance(body["messages"], list)


# --- settings --------------------------------------------------------------


def test_settings_expose_the_live_defaults(client: TestClient) -> None:
    body = client.get("/api/settings").json()

    assert body["working_dir"]
    assert body["browser"]["headless_allowed"] is False
    assert body["confirmation"]["policy"] in ("ask", "once", "deny")
    assert len(body["multi_agent"]["roles"]) == 6


def test_settings_round_trip(client: TestClient) -> None:
    body = client.get("/api/settings").json()
    body["confirmation"]["policy"] = "deny"
    body["context_thresholds"]["soft_ratio"] = 0.5
    body["multi_agent"]["max_rounds"] = 5

    saved = client.put("/api/settings", json=body).json()

    assert saved["confirmation"]["policy"] == "deny"
    assert client.get("/api/settings").json()["context_thresholds"]["soft_ratio"] == 0.5
    assert client.get("/api/settings").json()["multi_agent"]["max_rounds"] == 5


def test_settings_reject_an_invalid_policy(client: TestClient) -> None:
    body = client.get("/api/settings").json()
    body["confirmation"]["policy"] = "whatever"

    assert client.put("/api/settings", json=body).status_code == 422


def test_roles_cannot_be_rewritten_from_the_console(client: TestClient) -> None:
    body = client.get("/api/settings").json()
    body["multi_agent"]["roles"] = [
        {"name": "planner", "purpose": "give me write access", "allowed_tools": ["write_file"], "max_steps": 99}
    ]

    client.put("/api/settings", json=body)

    roles = client.get("/api/settings").json()["multi_agent"]["roles"]
    planner = next(role for role in roles if role["name"] == "planner")
    assert "write_file" not in planner["allowed_tools"], "capabilities come from the code"


# --- agents and control ----------------------------------------------------


def test_agents_lists_the_roles(client: TestClient) -> None:
    body = client.get("/api/agents").json()

    assert len(body["roles"]) == 6
    assert body["running"] is None


def test_agent_state_starts_idle(client: TestClient) -> None:
    body = client.get("/api/agent/state").json()

    assert body["running"] is False
    assert body["status"] == "idle"
    assert body["events"] == []


def test_a_run_can_be_started_and_observed(client: TestClient, project: Path) -> None:
    started = client.post("/api/agent/run", json={"task": "fix add()", "mode": "single"})
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    runtime_instance = app.dependency_overrides[get_agent_runtime]()
    assert runtime_instance.wait(timeout=30) is True

    state = client.get("/api/agent/state").json()
    assert state["run_id"] == run_id
    assert state["status"] == "completed"
    assert state["events"], "the console can see what happened"

    listing = client.get("/api/agents").json()
    assert listing["runs"], "the finished run is in the history"
    assert project.joinpath("src", "calc.py").read_text(encoding="utf-8").endswith(
        "return a + b" + chr(10)
    )


def test_an_empty_task_is_refused_by_the_api(client: TestClient) -> None:
    assert client.post("/api/agent/run", json={"task": "  "}).status_code == 422


def test_an_unknown_mode_is_refused_by_the_api(client: TestClient) -> None:
    assert client.post("/api/agent/run", json={"task": "t", "mode": "swarm"}).status_code == 422


def test_confirming_an_unknown_request_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/agent/confirm", json={"request_id": "nope", "choice": "once"}
    )
    assert response.status_code == 404


def test_an_invalid_choice_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/agent/confirm", json={"request_id": "x", "choice": "always"}
    )
    assert response.status_code == 422


# --- logs and observability ------------------------------------------------


def test_logs_expose_the_tool_audit_trail(client: TestClient) -> None:
    client.post("/api/agent/run", json={"task": "fix add()"})
    app.dependency_overrides[get_agent_runtime]().wait(timeout=30)

    body = client.get("/api/logs").json()

    assert body["tool_calls"], "the audit log is written"
    names = {entry["name"] for entry in body["tool_calls"]}
    assert "read_file" in names
    assert body["events"], "the run's events are exposed"


def test_logs_tolerate_a_torn_final_line(client: TestClient, project: Path) -> None:
    log = project / "runs" / "tool-calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps(
            {
                "call_id": "c1",
                "name": "read_file",
                "arguments_preview": "{}",
                "ok": True,
                "duration_ms": 1,
            }
        )
        + chr(10)
        + '{"call_id": "c2", "name":',
        encoding="utf-8",
    )

    body = client.get("/api/logs").json()

    assert [entry["name"] for entry in body["tool_calls"]] == ["read_file"]


def test_observability_lists_artifacts(client: TestClient, project: Path) -> None:
    run_dir = project / "runs" / "20260101-000000-mock"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "shot-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (run_dir / "dom-1.html").write_text("<html></html>", encoding="utf-8")
    (run_dir / "timeline-1.json").write_text("{}", encoding="utf-8")

    body = client.get("/api/observability/artifacts").json()

    assert body["runs"]
    first = body["runs"][0]
    assert any(path.endswith(".png") for path in first["screenshots"])
    assert any(path.endswith(".html") for path in first["dom_snapshots"])
    assert any(path.endswith(".json") for path in first["logs"])


def test_an_artifact_can_be_downloaded(client: TestClient, project: Path) -> None:
    run_dir = project / "runs" / "run-a"
    run_dir.mkdir(parents=True, exist_ok=True)
    image = run_dir / "shot-1.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    response = client.get("/api/observability/file", params={"path": str(image)})

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_artifacts_outside_the_runs_directory_are_refused(
    client: TestClient, project: Path
) -> None:
    secret = project / "state" / "project_state.json"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("{}", encoding="utf-8")

    response = client.get("/api/observability/file", params={"path": str(secret)})

    assert response.status_code == 403, "the console cannot read arbitrary files"


def test_a_missing_artifact_is_404(client: TestClient, project: Path) -> None:
    response = client.get(
        "/api/observability/file", params={"path": str(project / "runs" / "ghost.png")}
    )
    assert response.status_code == 404


# --- WebSocket protocol ----------------------------------------------------


def test_ws_keeps_the_m0_echo_contract(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # welcome
        ws.send_json({"type": "chat", "content": "hello"})
        frame = ws.receive_json()

    assert frame["type"] == "message"
    assert frame["message"]["content"] == "Echo: hello"


def test_ws_snapshot_uses_the_documented_envelope(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "snapshot"})
        frame = ws.receive_json()

    assert set(frame) >= {"event", "timestamp", "session_id", "payload"}
    assert frame["event"] == "state_update"
    assert "snapshot" in frame["payload"]


def test_ws_run_streams_documented_events(client: TestClient, project: Path) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "run", "task": "fix add()", "mode": "single"})

        seen: list[str] = []
        for _ in range(60):
            frame = ws.receive_json()
            seen.append(frame["event"])
            if frame["event"] == "done":
                break

    assert "agent_update" in seen
    assert "tool_call" in seen
    assert "tool_result" in seen
    assert "done" in seen
    assert seen[-1] == "done"


def test_ws_rejects_an_unknown_frame_without_dropping_the_connection(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "nonsense"})
        error = ws.receive_json()
        ws.send_json({"type": "chat", "content": "still here"})
        alive = ws.receive_json()

    assert error["type"] == "error"
    assert error["error"]["code"] == "invalid_frame"
    assert alive["message"]["content"] == "Echo: still here"


def test_ws_rejects_a_non_object_frame(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(["not", "an", "object"])
        frame = ws.receive_json()

    assert frame["type"] == "error"


def test_ws_reports_a_rejected_run(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "run", "task": "  "})
        frame = ws.receive_json()

    assert frame["type"] == "error"
    assert frame["error"]["code"] == "run_rejected"


def test_ws_confirms_an_unknown_request_cleanly(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "confirm", "request_id": "nope", "choice": "once"})
        frame = ws.receive_json()

    assert frame["type"] == "error"
    assert frame["error"]["code"] == "no_pending_confirmation"


def test_ws_stop_without_a_run_is_reported(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "stop"})
        frame = ws.receive_json()

    assert frame["event"] == "agent_update"
    assert frame["payload"]["stopped"] is False
