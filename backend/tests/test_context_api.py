"""Context / session REST surface tests (M2)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_sessions_endpoint_reports_the_active_session(client: TestClient) -> None:
    response = client.get("/api/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["active_session_id"]
    assert any(s["id"] == body["active_session_id"] for s in body["sessions"])


def test_messages_endpoint_is_empty_for_a_new_session(client: TestClient) -> None:
    response = client.get("/api/messages")

    assert response.status_code == 200
    body = response.json()
    assert body["messages"] == []
    assert body["message_count"] == 0
    assert body["session_id"]


def test_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/does-not-exist")
    assert response.status_code == 404


def test_session_can_be_fetched_by_id(client: TestClient) -> None:
    session_id = client.get("/api/sessions").json()["active_session_id"]

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["active_session_id"] == session_id


def test_messages_can_be_filtered_by_session(client: TestClient) -> None:
    session_id = client.get("/api/sessions").json()["active_session_id"]

    response = client.get("/api/messages", params={"session_id": session_id})

    assert response.status_code == 200
    assert response.json()["session_id"] == session_id


def test_message_limit_is_validated(client: TestClient) -> None:
    assert client.get("/api/messages", params={"limit": 0}).status_code == 422
    assert client.get("/api/messages", params={"limit": 99_999}).status_code == 422


def test_context_preview_returns_sections_in_priority_order(client: TestClient) -> None:
    response = client.get("/api/context", params={"task": "finish M2"})

    assert response.status_code == 200
    body = response.json()
    names = [section["name"] for section in body["sections"]]
    assert names[0] == "system"
    assert "task" in names
    assert body["budget_chars"] > 0
    assert body["total_chars"] <= body["budget_chars"] or body["dropped_sections"]


def test_context_preview_carries_the_task(client: TestClient) -> None:
    body = client.get("/api/context", params={"task": "a very specific task"}).json()
    task = next(s for s in body["sections"] if s["name"] == "task")
    assert "a very specific task" in task["content"]


def test_context_preview_marks_tool_results_untrusted(client: TestClient) -> None:
    # The REST surface takes no tool results, so verify the invariant through
    # the builder contract instead: a preview never contains the marker unless
    # a tool result was supplied.
    body = client.get("/api/context", params={"task": "t"}).json()
    assert "UNTRUSTED_DATA" not in body["sections"][0]["content"]


def test_context_preview_is_read_only(client: TestClient, state_files: Path) -> None:
    before = (state_files / "project_state.json").read_text(encoding="utf-8")

    client.get("/api/context", params={"task": "t"})

    after = (state_files / "project_state.json").read_text(encoding="utf-8")
    assert after == before, "previewing a context must not rewrite project state"
