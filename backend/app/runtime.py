"""Agent runtime (M8): run a task from the console and observe it live.

The console needs three things the CLI cannot give it: progress while the run
is happening, a stop button, and an answerable confirmation. This module owns
all three for exactly ONE run at a time.

Design notes

* the run happens on a worker thread, so the API stays responsive
* events are appended to a bounded ring and pushed to whatever thread is
  streaming through the subscription; a late client replays from the ring
* the stop button sets a flag the agent loop already checks before every step
* a confirmation blocks the worker until the console answers, or until its TTL
  expires — an unanswered prompt must not hang a run forever
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agents.checkpoint import CheckpointStore
from .agents.llm import ModelClient
from .agents.loop import DEFAULT_SYSTEM, AgentLoop
from .agents.models import AgentEvent, LoopLimits, safe_event
from .agents.orchestrator import AgentOrchestrator, OrchestrationLimits
from .agents.roles import DEFAULT_ROLES
from .config import runs_dir
from .context.builder import ContextBuilder
from .context.session import SessionManager
from .safety import SafetyLayer
from .settings import SettingsStore
from .storage import StateStore
from .tools import Executor, ToolContext, build_default_registry

EVENT_BUFFER = 500
CONFIRM_TIMEOUT_SECONDS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunRecord:
    """What the console shows about one run."""

    def __init__(self, run_id: str, task: str, mode: str) -> None:
        self.run_id = run_id
        self.task = task
        self.mode = mode
        self.status = "running"
        self.reason = ""
        self.round_count = 0
        self.tool_calls = 0
        self.started_at = _now()
        self.finished_at: datetime | None = None
        self.duration_ms = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "mode": self.mode,
            "status": self.status,
            "reason": self.reason,
            "round_count": self.round_count,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class AgentRuntime:
    """One console-facing run at a time."""

    def __init__(
        self,
        sessions: SessionManager | None = None,
        settings: SettingsStore | None = None,
        model_factory: Callable[[], ModelClient] | None = None,
    ) -> None:
        self.sessions = sessions or SessionManager()
        self.settings_store = settings or SettingsStore()
        self.store = self.sessions.store if self.sessions else StateStore()
        self.builder = ContextBuilder(
            self.sessions.transcript, self.sessions.memory, self.store
        )
        self.model_factory = model_factory

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._events: deque[AgentEvent] = deque(maxlen=EVENT_BUFFER)
        self._record: RunRecord | None = None
        self._history: deque[RunRecord] = deque(maxlen=50)

        self._pending_confirm: dict[str, Any] = {}
        self._confirm_queue: queue.Queue[str] = queue.Queue()
        self._subscribers: list[Callable[[AgentEvent], None]] = []
        self._idle = threading.Event()
        self._idle.set()

    # -- observation -------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def record(self) -> RunRecord | None:
        return self._record

    def events(self) -> list[AgentEvent]:
        return list(self._events)

    def history(self) -> list[RunRecord]:
        return list(self._history)

    def subscribe(self, handler: Callable[[AgentEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subscribers:
                    self._subscribers.remove(handler)

        return unsubscribe

    def _publish(self, event: AgentEvent) -> None:
        self._events.append(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for handler in subscribers:
            try:
                handler(event)
            except Exception:  # pragma: no cover - a dead subscriber must not break a run
                pass

    # -- control -----------------------------------------------------------

    def stop(self, run_id: str | None = None) -> bool:
        """Ask the running task to stop at the next step boundary."""
        record = self._record
        if record is None or not self.running:
            return False
        if run_id is not None and run_id != record.run_id:
            return False
        self._stop.set()
        # An unanswered confirmation would otherwise hold the worker.
        try:
            self._confirm_queue.put_nowait("reject")
        except queue.Empty:  # pragma: no cover
            pass
        self._publish(
            safe_event(
                "agent_update",
                0,
                message="stop requested by the console",
                data={"status": "stopping"},
            )
        )
        return True

    def confirm(self, request_id: str, choice: str) -> bool:
        """Answer a pending confirmation from the console."""
        if choice not in ("reject", "once", "session"):
            return False
        pending = self._pending_confirm.get(request_id)
        if pending is None:
            return False
        self._confirm_queue.put(choice)
        return True

    def pending_confirmation(self) -> dict[str, Any] | None:
        for request in self._pending_confirm.values():
            return request
        return None

    def _ask_confirmation(self, request: Any) -> str:
        """The hook the Executor's safety layer calls."""
        payload = dict(request or {})
        request_id = str(payload.get("id") or uuid.uuid4().hex[:12])
        payload["request_id"] = request_id
        policy = self.settings_store.load().confirmation.policy

        if policy == "deny":
            self._publish(
                safe_event(
                    "confirm_request",
                    0,
                    message="denied by the confirmation policy",
                    tool=str(payload.get("tool", "")),
                    ok=False,
                    data={**payload, "answer": "reject"},
                )
            )
            return "reject"
        if policy == "auto_once":
            self._publish(
                safe_event(
                    "confirm_request",
                    0,
                    message="auto-approved by the confirmation policy",
                    tool=str(payload.get("tool", "")),
                    ok=True,
                    data={**payload, "answer": "once"},
                )
            )
            return "once"

        # policy == "ask": publish and wait for the console.
        self._pending_confirm[request_id] = payload
        self._publish(
            safe_event(
                "confirm_request",
                0,
                message="waiting for confirmation",
                tool=str(payload.get("tool", "")),
                data=payload,
            )
        )
        try:
            choice = self._confirm_queue.get(timeout=CONFIRM_TIMEOUT_SECONDS)
        except queue.Empty:
            choice = "reject"
            self._publish(
                safe_event(
                    "agent_update",
                    0,
                    message="confirmation timed out; treated as a rejection",
                    ok=False,
                    data={"request_id": request_id},
                )
            )
        finally:
            self._pending_confirm.pop(request_id, None)
        return choice

    # -- starting work -----------------------------------------------------

    def start(
        self,
        task: str,
        mode: str = "single",
        max_steps: int | None = None,
        max_rounds: int | None = None,
        auto_confirm: bool | None = None,
    ) -> RunRecord:
        """Start a run. Raises RuntimeError when one is already going."""
        if self.running:
            raise RuntimeError("a run is already in progress")

        text = (task or "").strip()
        if not text:
            raise ValueError("task must not be empty")
        if mode not in ("single", "multi"):
            raise ValueError("mode must be 'single' or 'multi'")

        settings = self.settings_store.load()
        if auto_confirm:
            settings.confirmation.policy = "auto_once"

        run_id = uuid.uuid4().hex[:12]
        record = RunRecord(run_id, text, mode)
        with self._lock:
            self._record = record
            self._history.append(record)
            self._events.clear()
        self._stop.clear()
        while not self._confirm_queue.empty():
            try:
                self._confirm_queue.get_nowait()
            except queue.Empty:  # pragma: no cover
                break
        self._idle.clear()

        self._thread = threading.Thread(
            target=self._run,
            args=(record, text, mode, settings, max_steps, max_rounds),
            name="agent-run-" + run_id,
            daemon=True,
        )
        self._thread.start()
        return record

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the run settles (used by the tests and the CLI)."""
        return self._idle.wait(timeout)

    # -- the worker --------------------------------------------------------

    def _run(
        self,
        record: RunRecord,
        task: str,
        mode: str,
        settings: Any,
        max_steps: int | None,
        max_rounds: int | None,
    ) -> None:
        started = time.monotonic()
        try:
            self.sessions.start()
            self.sessions.record("user", task)

            working_dir = Path(settings.working_dir or Path.cwd())
            context = ToolContext(
                working_dir=working_dir,
                store=self.store,
                memory=self.sessions.memory,
            )
            registry = build_default_registry(context)
            safety = SafetyLayer.for_project(working_dir)
            checkpoints = CheckpointStore()
            log_path = runs_dir() / "tool-calls.jsonl"

            publish = self._publish

            def confirm_hook(request: Any) -> str:
                return self._ask_confirmation(request)

            if mode == "multi":
                limits = OrchestrationLimits(
                    max_rounds=max_rounds or settings.multi_agent.max_rounds,
                    stall_threshold=settings.multi_agent.stall_threshold,
                    max_steps=max_steps or 25,
                )
                orchestrator = AgentOrchestrator(
                    self._model(),
                    self.sessions,
                    context,
                    builder=self.builder,
                    limits=limits,
                    registry=registry,
                    safety=safety,
                    checkpoints=checkpoints,
                    on_event=publish,
                    confirm=confirm_hook,
                    log_path=log_path,
                )
                result = orchestrator.run(task, run_id=record.run_id)
                record.status = result.status
                record.reason = result.reason
                record.round_count = result.round_count
                record.tool_calls = result.tool_calls
            else:
                loop = AgentLoop(
                    self._model(),
                    Executor(registry, context, log_path=log_path, safety=safety),
                    self.sessions,
                    builder=self.builder,
                    limits=LoopLimits(
                        max_steps=max_steps or 25,
                        timeout_ms=settings.confirmation.ttl_seconds * 20_000,
                    ),
                    checkpoints=checkpoints,
                    safety=safety,
                    system=DEFAULT_SYSTEM,
                    on_event=publish,
                    should_stop=self._stop.is_set,
                    confirm=confirm_hook,
                    working_dir=working_dir,
                )
                result = loop.run(task, run_id=record.run_id)
                record.status = result.status
                record.reason = result.reason
                record.tool_calls = result.tool_calls

        except Exception as exc:  # noqa: BLE001 - the worker must never crash silently
            record.status = "error"
            record.reason = type(exc).__name__ + ": " + str(exc)
            self._publish(
                safe_event(
                    "error",
                    0,
                    message=record.reason,
                    ok=False,
                )
            )
        finally:
            record.finished_at = _now()
            record.duration_ms = int((time.monotonic() - started) * 1000)
            try:
                self._publish(
                    safe_event(
                        "done",
                        0,
                        record.status + (": " + record.reason if record.reason else ""),
                        ok=record.status == "completed",
                        data={
                            "status": record.status,
                            "reason": record.reason,
                            "tool_calls": record.tool_calls,
                            "round_count": record.round_count,
                            "duration_ms": record.duration_ms,
                            "run_id": record.run_id,
                        },
                    )
                )
            finally:
                # The run is over no matter what happened while announcing it:
                # a failure here must never leave wait() hanging.
                self._idle.set()

    def _model(self) -> ModelClient:
        if self.model_factory is not None:
            return self.model_factory()
        raise RuntimeError(
            "no model is configured for the console: a run needs a ModelClient"
        )

    # -- roles -------------------------------------------------------------

    @staticmethod
    def roles() -> list[dict[str, Any]]:
        return [
            {
                "name": role.name,
                "purpose": role.purpose,
                "allowed_tools": list(role.allowed_tools),
                "max_steps": role.max_steps,
                "verdict_kind": role.verdict_kind,
            }
            for role in DEFAULT_ROLES.values()
        ]