"""Executor: the single real entry point for running a tool.

docs/safety.md fixes the chain:

    ToolCall -> Validation -> SafetyLayer -> Confirmation -> Executor -> Tool

Every call is assessed by the SafetyLayer (M4) before anything runs. There is
no code path that reaches a tool handler without one: when the caller does not
supply a layer, the Executor builds one scoped to the working directory, so the
default is still "checked", never "unchecked".

The Executor also owns what docs/safety.md requires of it: schema validation,
logging, error handling and idempotency.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pydantic import ValidationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..safety import SafetyLayer

from .builtin import ToolContext, ToolOutcome, build_default_registry
from .errors import (
    ConfirmationRequiredError,
    SafetyBlockedError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from .models import ToolCall, ToolCallLogEntry, ToolErrorInfo, ToolResult
from .registry import ToolRegistry

# An approval hook returns True to allow the call (a non-interactive way to
# answer the confirmation the SafetyLayer asks for).
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
        safety: "SafetyLayer | None" = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.context = context
        self.log_path = Path(log_path) if log_path is not None else None
        self.approval = approval
        self.replay_cache = replay_cache
        # Imported here rather than at module scope so app.tools and app.safety
        # do not import each other at package initialisation time.
        if safety is None:
            from ..safety import SafetyLayer

            working_dir = (
                Path(context.working_dir) if context is not None else Path.cwd()
            )
            safety = SafetyLayer.for_project(working_dir)
        self.safety = safety
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

            # 1. Validation first, then the SafetyLayer — the documented order
            #    (ToolCall -> Validation -> SafetyLayer -> Confirmation).
            args = tool.args_model.model_validate(call.arguments)

            # 2. SafetyLayer: allow / confirm / deny, before anything runs.
            verdict = self.safety.assess(call, spec=tool.spec)
            if verdict.decision == "deny":
                raise SafetyBlockedError(
                    "blocked by the safety layer: " + "; ".join(verdict.reasons),
                    details={"reasons": verdict.reasons, "risk": verdict.risk},
                )
            if verdict.confirmation is not None and not confirmed:
                granted = self.approval is not None and self.approval(call)
                if not granted:
                    request = verdict.confirmation
                    raise ConfirmationRequiredError(
                        "tool " + call.name + " requires confirmation before it runs",
                        details={
                            "confirmation": request.model_dump(mode="json"),
                            "risk": verdict.risk,
                            "reasons": verdict.reasons,
                        },
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

            outcome = tool.handler(args, self.context)

            # 3. Guard the output: tool text is DATA, and any instruction-like
            #    content inside it is flagged rather than honoured.
            output, injection_findings = self.safety.guard_output(outcome.output)
            data = dict(outcome.data)
            data["untrusted"] = True
            if injection_findings:
                data["injection_findings"] = injection_findings

            finished_at = datetime.now(timezone.utc)
            result = ToolResult(
                tool_call_id=call.id,
                name=call.name,
                ok=True,
                output=output,
                risk=risk,
                duration_ms=int((time.monotonic() - started) * 1000),
                artifacts=list(outcome.artifacts),
                data=data,
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
