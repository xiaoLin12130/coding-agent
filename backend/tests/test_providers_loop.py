"""M9: one AgentLoop, several providers.

The point of the milestone is that the loop does not know which provider is
behind it. These tests run the SAME loop, over the SAME workspace, with a
scripted provider and with an HTTP provider whose transport is faked, and assert
the runs come out the same.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import AgentLoop, CheckpointStore, LoopLimits
from app.config import AppPaths, ENV_STATE_DIR
from app.context import ContextBuilder, SessionManager
from app.providers import default_registry
from app.providers.openai_compatible import HttpChatModel
from app.storage import StateStore
from app.tools import Executor, ToolContext, build_default_registry

SOURCE = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"

REPLIES = [
    json.dumps({"name": "read_file", "arguments": {"path": "src/calc.py"}}),
    json.dumps(
        {
            "name": "apply_patch",
            "arguments": {
                "path": "src/calc.py",
                "hunks": [{"old": "return a - b", "new": "return a + b"}],
            },
        }
    ),
    "Fixed add(): it sums now.",
]


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text(SOURCE, encoding="utf-8")
    return root


def run_task(project: Path, model) -> object:
    """Run one task through the real loop over the given model."""
    paths = AppPaths(
        project_root=project,
        state_dir=project,
        project_state_file=project / "project_state.json",
        memory_file=project / "memory.json",
    )
    store = StateStore(paths)
    context = ToolContext(working_dir=project, store=store)
    executor = Executor(
        build_default_registry(context), context, log_path=project / "runs" / "log.jsonl"
    )
    sessions = SessionManager(project / "state" / "sessions", store=store)
    builder = ContextBuilder(sessions.transcript, sessions.memory, sessions.store)
    loop = AgentLoop(
        model,
        executor,
        sessions,
        builder=builder,
        limits=LoopLimits(max_steps=6, timeout_ms=60_000),
        checkpoints=CheckpointStore(project / "state" / "checkpoints"),
        confirm=lambda request: "once",
    )
    return loop.run("fix the subtraction bug in src/calc.py")


def http_model(replies: list[str]) -> HttpChatModel:
    """An HTTP provider whose transport answers with the canned replies."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        text = queue.pop(0) if queue else "Done."
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
        )

    return HttpChatModel(
        base_url="http://model.test/v1", model="test-model", transport=httpx.MockTransport(handler)
    )


def test_the_same_loop_runs_over_every_provider(workspace: Path) -> None:
    """Two providers, two workspaces, identical outcomes."""
    scripted_project = workspace
    http_project = workspace.parent / "project-http"
    (http_project / "src").mkdir(parents=True)
    (http_project / "src" / "calc.py").write_text(SOURCE, encoding="utf-8")

    scripted = default_registry().create("scripted", replies=list(REPLIES))
    http = http_model(list(REPLIES))

    first = run_task(scripted_project, scripted)
    second = run_task(http_project, http)

    assert first.status == "completed", first.reason
    assert second.status == "completed", second.reason
    assert first.tool_summary() == second.tool_summary() == {"read_file": 1, "apply_patch": 1}
    assert (scripted_project / "src" / "calc.py").read_text(encoding="utf-8") == FIXED
    assert (http_project / "src" / "calc.py").read_text(encoding="utf-8") == FIXED


def test_the_http_provider_receives_the_loop_prompt(workspace: Path) -> None:
    """The adapter is a transport: the loop's prompt reaches the endpoint."""
    seen: list[str] = []
    replies = [
        json.dumps({"name": "read_file", "arguments": {"path": "src/calc.py"}}),
        "The file is read.",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen.append(body["messages"][-1]["content"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": replies.pop(0) if replies else "Done."}}]},
        )

    model = HttpChatModel(
        base_url="http://model.test/v1", model="test-model", transport=httpx.MockTransport(handler)
    )
    result = run_task(workspace, model)

    assert seen, "the endpoint was never called"
    assert "fix the subtraction bug" in seen[0]
    assert result.status == "completed", result.reason
    assert result.tool_calls == 1
    # the loop carried the tool result back to the endpoint
    assert "tool read_file -> ok" in seen[1]


def test_the_console_picks_the_provider_from_the_settings_document(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider choice is configuration: no code path changes."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv(ENV_STATE_DIR, str(state))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(["from the plan"]), encoding="utf-8")
    (state / "settings.json").write_text(
        json.dumps(
            {"provider": {"adapter": "scripted", "options": {"plan": str(plan)}}}
        ),
        encoding="utf-8",
    )

    from app import deps

    model = deps.build_console_model()
    assert model.name == "scripted"
    assert model.complete("hi").text == "from the plan"


def test_saving_a_new_provider_drops_the_cached_model(client: TestClient) -> None:
    from app import deps

    settings = client.get("/api/settings").json()
    assert [item["name"] for item in settings["provider"]["available"]] == [
        "browser",
        "openai_compatible",
        "scripted",
    ]

    deps.get_agent_runtime()
    assert deps._runtime is not None

    settings["provider"]["adapter"] = "scripted"
    settings["provider"]["options"] = {"plan": "plan.json"}
    saved = client.put("/api/settings", json=settings)
    assert saved.status_code == 200
    assert saved.json()["provider"]["adapter"] == "scripted"
    assert deps._runtime is None, "the next run must build the new provider"

    # the stored document never carries a secret option value
    assert saved.json()["provider"]["options"] == {"plan": "plan.json"}
