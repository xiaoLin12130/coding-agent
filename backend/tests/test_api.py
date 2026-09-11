"""Startup + REST surface tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import APP_NAME, APP_VERSION
from app.main import app


def test_app_starts_with_expected_metadata() -> None:
    assert app.title == APP_NAME
    assert app.version == APP_VERSION


def test_openapi_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/health" in paths
    assert "/api/project_state" in paths
    assert "/api/memory" in paths


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
    }


def test_project_state_endpoint_reads_persisted_file(client: TestClient) -> None:
    response = client.get("/api/project_state")
    assert response.status_code == 200
    body = response.json()
    assert body["current_milestone"] == "M0"
    assert body["current_task"] == "T1"
    assert body["todos"][0]["content"] == "skeleton"


def test_memory_endpoint_reads_persisted_file(client: TestClient) -> None:
    response = client.get("/api/memory")
    assert response.status_code == 200
    assert response.json()["memories"][0]["key"] == "stack"


def test_state_endpoints_tolerate_missing_files(tmp_path, monkeypatch) -> None:
    from app.config import ENV_STATE_DIR

    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path / "does-not-exist"))
    with TestClient(app) as test_client:
        state_response = test_client.get("/api/project_state")
        memory_response = test_client.get("/api/memory")

    assert state_response.status_code == 200
    assert state_response.json()["current_milestone"] is None
    assert state_response.json()["todos"] == []
    assert memory_response.status_code == 200
    assert memory_response.json()["memories"] == []
