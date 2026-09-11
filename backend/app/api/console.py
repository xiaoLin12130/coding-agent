"""Console REST surface (M8).

Sessions, messages, settings, logs, agents, observability and agent control.
Read-only where it can be: the only mutating routes are creating/archiving a
session, saving settings, and driving a run (start / stop / confirm), all of
which go through the runtime and therefore through the SafetyLayer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..agents.checkpoint import CheckpointStore
from ..config import runs_dir, state_dir
from ..context import SessionManager
from ..deps import get_agent_runtime, get_session_manager, reset_agent_runtime
from ..runtime import AgentRuntime
from ..settings import Settings, SettingsStore
from ..tools.models import ToolCallLogEntry

router = APIRouter()

TOOL_LOG_NAME = "tool-calls.jsonl"


# --- sessions --------------------------------------------------------------


@router.post("/sessions")
def create_session(
    payload: dict | None = None,
    title: Annotated[str | None, Query()] = None,
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    """Open a fresh session and make it active.

    The title may arrive as a JSON body ({"title": ...}) or as a query
    parameter; a client that sends both must still get one session.
    """
    from ..context.session import new_session_id

    body_title = ""
    if isinstance(payload, dict):
        body_title = str(payload.get("title") or "")
    session_id = new_session_id()
    snapshot = manager.start(session_id=session_id, title=body_title or title or "")
    return {"active_session_id": snapshot.active_session_id, "created": True}


@router.post("/sessions/{session_id}/archive")
def archive_session(
    session_id: str, manager: SessionManager = Depends(get_session_manager)
) -> dict:
    """Archive a session: summarise, copy the transcript, mark it archived."""
    if manager._index.find(session_id) is None and not manager.transcript.path_for(
        session_id
    ).exists():
        raise HTTPException(status_code=404, detail="unknown session " + session_id)
    if manager.current_session_id() == session_id:
        # rotating the ACTIVE session is the M6 flow: it opens a continuation
        rotation = manager.rotate(reason="manual")
        return {
            "session_id": rotation.archived_session_id,
            "archived": True,
            "continues_as": rotation.new_session_id,
        }
    manager.archive_session(session_id)
    return {"session_id": session_id, "archived": True}


# --- settings --------------------------------------------------------------


@router.get("/settings", response_model=Settings)
def read_settings() -> Settings:
    return SettingsStore().load()


@router.put("/settings", response_model=Settings)
def write_settings(settings: Settings) -> Settings:
    """Save the settings document.

    Changing the provider rebuilds the console's model: the next run has to use
    what the page now shows, not the adapter the process started with.
    """
    store = SettingsStore()
    previous = store.load()
    saved = store.save(settings)
    before, after = previous.provider, saved.provider
    if (
        before.adapter != after.adapter
        or before.name != after.name
        or before.model != after.model
        or before.options != after.options
    ):
        reset_agent_runtime()
    return saved


# --- logs ------------------------------------------------------------------


def _tool_log_path() -> Path:
    return runs_dir() / TOOL_LOG_NAME


@router.get("/logs")
def read_logs(
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> dict[str, Any]:
    """The tool audit log and the current run's events."""
    entries: list[dict] = []
    path = _tool_log_path()
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(ToolCallLogEntry.model_validate(json.loads(line)).model_dump(mode="json"))
            except Exception:
                # a torn final line must not break the console
                continue
    return {
        "tool_calls": entries,
        "events": [event.model_dump(mode="json") for event in runtime.events()],
    }


# --- agents ----------------------------------------------------------------


@router.get("/agents")
def read_agents(runtime: AgentRuntime = Depends(get_agent_runtime)) -> dict[str, Any]:
    record = runtime.record()
    return {
        "roles": AgentRuntime.roles(),
        "running": record.as_dict() if record and runtime.running else None,
        "runs": [item.as_dict() for item in reversed(runtime.history())],
    }


@router.get("/agent/state")
def agent_state(runtime: AgentRuntime = Depends(get_agent_runtime)) -> dict[str, Any]:
    record = runtime.record()
    return {
        "running": runtime.running,
        "run_id": record.run_id if record else None,
        "status": record.status if record else "idle",
        "task": record.task if record else "",
        "mode": record.mode if record else "",
        "events": [event.model_dump(mode="json") for event in runtime.events()],
        "pending_confirmation": runtime.pending_confirmation(),
    }


@router.post("/agent/run")
def start_run(
    payload: dict, runtime: AgentRuntime = Depends(get_agent_runtime)
) -> dict[str, Any]:
    """Start a run. The task text is DATA; the runtime types it as a task."""
    task = str(payload.get("task", ""))
    mode = str(payload.get("mode", "single"))
    try:
        record = runtime.start(
            task,
            mode=mode,
            max_steps=payload.get("max_steps"),
            max_rounds=payload.get("max_rounds"),
            auto_confirm=bool(payload.get("auto_confirm", False)),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": record.run_id, "accepted": True}


@router.post("/agent/stop")
def stop_run(
    payload: dict | None = None, runtime: AgentRuntime = Depends(get_agent_runtime)
) -> dict[str, Any]:
    run_id = (payload or {}).get("run_id")
    return {"run_id": run_id, "stopped": runtime.stop(run_id)}


@router.post("/agent/confirm")
def confirm_run(
    payload: dict, runtime: AgentRuntime = Depends(get_agent_runtime)
) -> dict[str, Any]:
    request_id = str(payload.get("request_id", ""))
    choice = str(payload.get("choice", ""))
    if choice not in ("reject", "once", "session"):
        raise HTTPException(status_code=422, detail="choice must be reject|once|session")
    if not runtime.confirm(request_id, choice):
        raise HTTPException(status_code=404, detail="no such pending confirmation")
    return {"accepted": True}


# --- observability ---------------------------------------------------------


@router.get("/observability/artifacts")
def list_artifacts(limit: Annotated[int, Query(ge=1, le=200)] = 20) -> dict[str, Any]:
    """Screenshots, DOM snapshots and logs written by browser runs."""
    root = runs_dir()
    if not root.exists():
        return {"runs": []}

    directories = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]

    runs: list[dict[str, Any]] = []
    for directory in directories:
        files = [path for path in directory.iterdir() if path.is_file()]
        runs.append(
            {
                "run_dir": str(directory),
                "screenshots": [str(p) for p in files if p.suffix.lower() == ".png"],
                "dom_snapshots": [
                    str(p) for p in files if p.suffix.lower() in (".html", ".txt")
                ],
                "logs": [str(p) for p in files if p.suffix.lower() == ".json"],
            }
        )
    return {"runs": runs}


@router.get("/observability/file")
def read_artifact(path: Annotated[str, Query()]) -> FileResponse:
    """Serve one artifact, restricted to the runs directory."""
    root = runs_dir().resolve()
    candidate = Path(path)
    try:
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not str(resolved).startswith(str(root)):
        raise HTTPException(status_code=403, detail="artifacts outside the runs directory are not served")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="no such artifact")
    return FileResponse(resolved)