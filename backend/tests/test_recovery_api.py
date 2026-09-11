"""Recovery REST surface tests (M6)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents import AgentLoop, CheckpointStore, LoopLimits, ScriptedModel
from app.config import AppPaths
from app.context import ContextBuilder, SessionManager
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry


def test_recovery_snapshot_describes_the_current_state(client: TestClient) -> None:
    response = client.get("/api/recovery")

    assert response.status_code == 200
    body = response.json()
    assert body["active_session_id"]
    assert body["session_message_count"] >= 0
    assert isinstance(body["archived_session_ids"], list)
    assert body["memory_count"] >= 0


def test_recovery_snapshot_includes_context_pressure_when_asked(client: TestClient) -> None:
    body = client.get("/api/recovery", params={"task": "finish M6"}).json()

    assert body["context_pressure"] is not None
    assert body["context_pressure"]["level"] in ("ok", "soft", "hard")


def test_pressure_endpoint_reports_the_level(client: TestClient) -> None:
    body = client.get("/api/recovery/pressure", params={"task": "a task"}).json()

    assert body["budget_chars"] > 0
    assert body["used_chars"] >= 0
    assert 0 <= body["ratio"] <= 1


def test_pressure_endpoint_validates_the_ratios(client: TestClient) -> None:
    assert client.get("/api/recovery/pressure", params={"soft_ratio": 1.5}).status_code == 422
    assert client.get("/api/recovery/pressure", params={"hard_ratio": 0}).status_code == 422


def test_pressure_endpoint_rejects_an_inverted_pair(client: TestClient) -> None:
    response = client.get(
        "/api/recovery/pressure", params={"soft_ratio": 0.95, "hard_ratio": 0.5}
    )

    assert response.status_code == 422
    assert "soft_ratio" in response.json()["detail"]


def test_runs_endpoint_is_empty_without_checkpoints(client: TestClient) -> None:
    response = client.get("/api/recovery/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_run_returns_404(client: TestClient) -> None:
    assert client.get("/api/recovery/runs/nope").status_code == 404


def test_a_pending_run_appears_and_can_be_fetched(tmp_path: Path, state_files: Path) -> None:
    """A run stopped by its step budget is offered for continuation."""
    project = state_files
    (project / "a.txt").write_text("x", encoding="utf-8")
    store = StateStore()
    context = ToolContext(working_dir=project, store=store)
    executor = Executor(build_default_registry(context), context)
    sessions = SessionManager(project / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    AgentLoop(
        ScriptedModel([json.dumps({"name": "read_file", "arguments": {"path": "a.txt"}})]),
        executor,
        sessions,
        builder=builder,
        checkpoints=CheckpointStore(project / "checkpoints"),
        limits=LoopLimits(max_steps=1),
    ).run("an unfinished task", run_id="api-run")

    # the API reads its own default locations, so point them at this directory
    import os

    from app.config import ENV_CHECKPOINTS_DIR

    os.environ[ENV_CHECKPOINTS_DIR] = str(project / "checkpoints")
    try:
        from app.main import app
        from fastapi.testclient import TestClient as TC

        with TC(app) as api:
            listing = api.get("/api/recovery/runs").json()
            assert [plan["run_id"] for plan in listing] == ["api-run"]
            assert listing[0]["task"] == "an unfinished task"

            one = api.get("/api/recovery/runs/api-run")
            assert one.status_code == 200
            assert one.json()["resumable"] is True
    finally:
        os.environ.pop(ENV_CHECKPOINTS_DIR, None)


def test_recovery_endpoints_do_not_mutate_state(client: TestClient, state_files: Path) -> None:
    before = (state_files / "project_state.json").read_text(encoding="utf-8")

    client.get("/api/recovery")
    client.get("/api/recovery/runs")
    client.get("/api/recovery/pressure", params={"task": "t"})

    after = (state_files / "project_state.json").read_text(encoding="utf-8")
    assert after == before
