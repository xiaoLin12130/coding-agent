"""Executor: the single real entry point for running a tool.

docs/safety.md fixes the chain:

    ToolCall -> Validation -> SafetyLayer -> Confirmation -> Executor -> Tool

M3 builds everything except SafetyLayer (that is M4). What M3 does provide is
the seam M4 plugs into: tools declare a risk level and whether they need
confirmation, and the Executor refuses to run a confirmation-requiring tool
unless an approval hook or an explicit confirmation is present. No policy
lives here — no path limits, no sensitive-file list, no UI.

The Executor also owns what docs/safety.md requires of it: schema validation,
logging, error handling and idempotency.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from .builtin import ToolContext, ToolOutcome, build_default_registry
from .errors import (
    ConfirmationRequiredError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from .models import ToolCall, ToolCallLogEntry, ToolErrorInfo, ToolResult
from .registry import ToolRegistry

# An approval hook returns True to allow the call. M4 replaces this with the
# real SafetyLayer + confirmation UI.
ApprovalHook = Callable[[ToolCall], bool]

LOG_FILE_NAME = "tool-calls.jsonl"


def idempotency_key(call: ToolCall) -> str:
    """Stable key for replaying a call with identical arguments."""
    canonical = json.dumps(
        {"name": call.name, "arguments": call.arguments},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Executor:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        context: ToolContext | None = None,
        log_path: Path | str | None = None,
        approval: ApprovalHook | None = None,
        replay_cache: bool = True,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.context = context
        self.log_path = Path(log_path) if log_path is not None else None
        self.approval = approval
        self.replay_cache = replay_cache
        self._cache: dict[str, ToolResult] = {}
        self._log: list[ToolCallLogEntry] = []

    # -- public API --------------------------------------------------------

    def execute(self, call: ToolCall, confirmed: bool = False) -> ToolResult:
        """Run one tool call and never raise: failures become ToolResult."""
        started = time.monotonic()
        started_at = datetime.now(timezone.utc)
        risk = "low"
        replay = False

        try:
            tool = self.registry.get(call.name)  # raises ToolNotFoundError
            risk = tool.spec.risk

            if tool.spec.requires_confirmation and not (
                confirmed or (self.approval is not None and self.approval(call))
            ):
                raise ConfirmationRequiredError(
                    "tool " + call.name + " requires confirmation before it runs"
                )

            key = idempotency_key(call)
            if tool.spec.idempotent and self.replay_cache:
                cached = self._cache.get(key)
                if cached is not None:
                    replayed = cached.model_copy(
                        update={
                            "idempotent_replay": True,
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        }
                    )
                    # A replay is still a call that happened: it must appear in
                    # the audit log, or the log would silently under-report.
                    self._record(replayed, call, True)
                    return replayed

            args = tool.args_model.model_validate(call.arguments)
            outcome = tool.handler(args, self.context)

            finished_at = datetime.now(timezone.utc)
            result = ToolResult(
                tool_call_id=call.id,
                name=call.name,
                ok=True,
                output=outcome.output,
                risk=risk,
                duration_ms=int((time.monotonic() - started) * 1000),
                artifacts=list(outcome.artifacts),
                data=dict(outcome.data),
                started_at=started_at,
                finished_at=finished_at,
            )
            if tool.spec.idempotent and self.replay_cache:
                self._cache[key] = result

        except ValidationError as exc:
            result = self._failure(
                call,
                risk,
                ToolErrorInfo(
                    code="invalid_arguments",
                    message="the arguments do not match the tool schema",
                    details={"errors": _validation_details(exc)},
                    retryable=True,
                ),
                started,
                started_at,
            )
        except ToolError as exc:
            details = dict(getattr(exc, "details", {}) or {})
            result = self._failure(
                call,
                risk,
                ToolErrorInfo(
                    code=exc.code,
                    message=str(exc),
                    details=details,
                    retryable=exc.retryable,
                ),
                started,
                started_at,
            )
        except Exception as exc:  # noqa: BLE001 - the boundary must not leak
            result = self._failure(
                call,
                risk,
                ToolErrorInfo(
                    code="internal_error",
                    message="the tool failed unexpectedly: " + type(exc).__name__ + ": " + str(exc),
                    retryable=False,
                ),
                started,
                started_at,
            )

        self._record(result, call, confirmed or replay)
        return result

    def execute_all(
        self, calls: list[ToolCall], confirmed: bool = False
    ) -> list[ToolResult]:
        return [self.execute(call, confirmed=confirmed) for call in calls]

    # -- logging -----------------------------------------------------------

    @property
    def log(self) -> list[ToolCallLogEntry]:
        return list(self._log)

    def _record(self, result: ToolResult, call: ToolCall, confirmed: bool) -> None:
        entry = ToolCallLogEntry(
            call_id=call.id,
            name=call.name,
            arguments_preview=_preview(call.arguments),
            ok=result.ok,
            error_code=result.error.code if result.error else None,
            duration_ms=result.duration_ms,
            idempotent_replay=result.idempotent_replay,
            confirmed=confirmed,
        )
        self._log.append(entry)
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n"
                )
        except OSError:
            # Logging must never break an execution.
            pass

    # -- helpers -----------------------------------------------------------

    def _failure(
        self,
        call: ToolCall,
        risk: str,
        error: ToolErrorInfo,
        started: float,
        started_at: datetime,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            ok=False,
            output="",
            error=error,
            risk=risk,  # type: ignore[arg-type]
            duration_ms=int((time.monotonic() - started) * 1000),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )


def _validation_details(exc: ValidationError) -> list[dict]:
    details = []
    for item in exc.errors():
        details.append(
            {
                "location": [str(part) for part in item.get("loc", ())],
                "message": item.get("msg", ""),
                "type": item.get("type", ""),
            }
        )
    return details


def _preview(arguments: dict, limit: int = 200) -> str:
    text = json.dumps(arguments, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


__all__ = [
    "ApprovalHook",
    "Executor",
    "LOG_FILE_NAME",
    "ToolContext",
    "ToolOutcome",
    "ToolNotFoundError",
    "ToolValidationError",
    "ToolExecutionError",
    "idempotency_key",
]
