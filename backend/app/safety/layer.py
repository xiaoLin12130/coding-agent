"""SafetyLayer: the gate every tool call passes through.

docs/safety.md:

    ToolCall -> Validation -> SafetyLayer -> Confirmation -> Executor -> Tool

The layer decides allow / confirm / deny, produces the confirmation request the
human sees, remembers session grants, and marks tool output as untrusted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from .injection import (
    InjectedInstructionError,
    assert_instruction_source,
    scan_untrusted,
)
from .models import (
    ConfirmationChoice,
    ConfirmationRequest,
    RiskLevel,
    SafetyVerdict,
    utc_now,
)
from .paths import FilesystemPolicy
from .policy import SafetyPolicy
from .shell import ShellGrader

# Tool name -> which argument carries a path the policy must check.
PATH_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "list_dir": ("path",),
    "read_file": ("path",),
    "write_file": ("path",),
    "apply_patch": ("path",),
    "search": ("path",),
}
DEFAULT_CONFIRMATION_TTL_SECONDS = 300


class SafetyLayer:
    def __init__(self, policy: SafetyPolicy) -> None:
        self.policy = policy
        self.filesystem = FilesystemPolicy(policy)
        self.shell = ShellGrader(policy, self.filesystem)
        self._grants: dict[str, str] = {}
        self._pending: dict[str, ConfirmationRequest] = {}

    # -- construction ------------------------------------------------------

    @classmethod
    def for_project(
        cls,
        project_root: Path | str,
        extra_roots: list[Path | str] | None = None,
    ) -> "SafetyLayer":
        policy = SafetyPolicy(
            project_root=Path(project_root).resolve(),
            extra_roots=[Path(root).resolve() for root in (extra_roots or [])],
        )
        return cls(policy)

    # -- assessment --------------------------------------------------------

    def assess(self, call: Any, spec: Any = None) -> SafetyVerdict:
        """Decide allow / confirm / deny for one ToolCall.

        Called AFTER argument validation, so path arguments are strings by now.
        'spec' is the tool's ToolSpec when the caller has it; the declared risk
        is then authoritative and the policy only adds path and shell checks.
        """
        name = getattr(call, "name", "")
        arguments = dict(getattr(call, "arguments", {}) or {})

        # 1. paths: the part no tool may bypass
        for key in PATH_ARGUMENTS.get(name, ()):
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            decision = self.filesystem.check(value, self.policy.project_root)
            if not decision.allowed:
                return SafetyVerdict(
                    decision="deny",
                    risk="high",
                    reasons=[name + ": " + decision.reason + " (" + str(decision.resolved) + ")"],
                )

        # 2. shell commands get graded, whatever the tool declares
        if name == "run_shell":
            return self._assess_shell(call, arguments)

        # 3. otherwise the tool's own declaration decides
        declared = getattr(spec, "risk", None) if spec is not None else None
        requires = bool(getattr(spec, "requires_confirmation", False)) if spec is not None else False
        risk: RiskLevel = declared or ("low" if name in self.policy.read_only_tools else "medium")

        if requires or risk == "high":
            grant_key = self._grant_key(call)
            if grant_key in self._grants:
                return SafetyVerdict(
                    decision="allow",
                    risk=risk,
                    reasons=["allowed by a session grant"],
                    granted_by="session_grant",
                )
            reasons = [name + " is declared " + risk + " risk"]
            return SafetyVerdict(
                decision="confirm",
                risk=risk,
                reasons=reasons,
                confirmation=self._confirmation(call, risk, reasons),
            )
        return SafetyVerdict(
            decision="allow", risk=risk, reasons=[name + " is declared " + risk + " risk"]
        )

    def _assess_shell(self, call: Any, arguments: dict) -> SafetyVerdict:
        command = str(arguments.get("command", ""))
        cwd = arguments.get("cwd")
        if cwd is not None:
            decision = self.filesystem.check(cwd, self.policy.project_root)
            if not decision.allowed:
                return SafetyVerdict(
                    decision="deny",
                    risk="high",
                    reasons=["run_shell: " + decision.reason],
                )
        assessment = self.shell.assess(command, cwd=str(cwd) if cwd else None)

        if assessment.deny:
            return SafetyVerdict(
                decision="deny",
                risk="high",
                reasons=[assessment.deny_reason or "denied by policy"],
            )

        risk: RiskLevel = assessment.risk
        always_confirm = "run_shell" in self.policy.always_confirm_tools
        needs_confirmation = risk == "high" or always_confirm
        reasons = list(assessment.reasons)
        if always_confirm and risk != "high":
            reasons.append(
                "shell commands are always confirmed, even when the command itself looks harmless"
            )

        if needs_confirmation:
            grant_key = self._grant_key(call)
            if grant_key in self._grants:
                return SafetyVerdict(
                    decision="allow",
                    risk=risk,
                    reasons=reasons + ["allowed by a session grant"],
                    granted_by="session_grant",
                )
            return SafetyVerdict(
                decision="confirm",
                risk=risk,
                reasons=reasons,
                confirmation=self._confirmation(call, risk, reasons, command=command, cwd=cwd),
            )
        return SafetyVerdict(decision="allow", risk=risk, reasons=reasons)

    def _confirmation(
        self,
        call: Any,
        risk: RiskLevel,
        reasons: list[str],
        command: str = "",
        cwd: Any = None,
    ) -> ConfirmationRequest:
        arguments = dict(getattr(call, "arguments", {}) or {})
        impact = self._impact(call, arguments)
        request = ConfirmationRequest(
            id=uuid.uuid4().hex[:12],
            tool=getattr(call, "name", ""),
            risk=risk,
            command=command or self._command_preview(getattr(call, "name", ""), arguments),
            cwd=str(cwd) if cwd else str(self.policy.project_root),
            impact=impact,
            reasons=reasons,
            arguments=arguments,
            expires_at=utc_now() + timedelta(seconds=DEFAULT_CONFIRMATION_TTL_SECONDS),
        )
        self._pending[request.id] = request
        return request

    @staticmethod
    def _command_preview(name: str, arguments: dict) -> str:
        if name == "run_shell":
            return str(arguments.get("command", ""))
        rendered = ", ".join(
            str(key) + "=" + str(value)[:60] for key, value in sorted(arguments.items())
        )
        return name + "(" + rendered + ")"

    def _impact(self, call: Any, arguments: dict) -> list[str]:
        name = getattr(call, "name", "")
        impact: list[str] = []
        for key in PATH_ARGUMENTS.get(name, ()):
            if key in arguments:
                resolved = self.filesystem.resolve(arguments[key], self.policy.project_root)
                impact.append(("writes " if name in self.policy.write_tools else "reads ") + str(resolved))
        if name == "run_shell":
            impact.append("runs a shell command in " + str(arguments.get("cwd") or self.policy.project_root))
            assessment = self.shell.assess(str(arguments.get("command", "")))
            if assessment.outside_paths:
                impact.append("mentions paths outside the project: " + ", ".join(assessment.outside_paths[:3]))
        if name == "update_project_state":
            impact.append("rewrites state/project_state.json")
        if name == "memory_propose":
            impact.append("may add one entry to state/memory.json")
        if not impact:
            impact.append("no filesystem effect declared")
        return impact

    # -- grants ------------------------------------------------------------

    def _grant_key(self, call: Any) -> str:
        arguments = dict(getattr(call, "arguments", {}) or {})
        name = getattr(call, "name", "")
        if name == "run_shell":
            # A session grant covers this command shape, not every command.
            return name + ":" + " ".join(str(arguments.get("command", "")).split())[:200]
        return name + ":" + str(sorted(arguments.items()))[:200]

    def decide(self, call: Any, choice: ConfirmationChoice) -> SafetyVerdict:
        """Record the human's answer and return the resulting verdict."""
        if choice == "reject":
            return SafetyVerdict(
                decision="deny", risk="high", reasons=["rejected by the user"]
            )
        if choice == "once":
            return SafetyVerdict(
                decision="allow", risk="high", reasons=["approved once"], granted_by="confirmation"
            )
        if choice == "session":
            self._grants[self._grant_key(call)] = "session"
            return SafetyVerdict(
                decision="allow",
                risk="high",
                reasons=["approved for this session"],
                granted_by="session_grant",
            )
        raise ValueError("unknown confirmation choice " + repr(choice))

    def has_session_grant(self, call: Any) -> bool:
        return self._grant_key(call) in self._grants

    def grants(self) -> dict[str, str]:
        return dict(self._grants)

    def revoke_all(self) -> None:
        self._grants.clear()

    def pending(self) -> list[ConfirmationRequest]:
        return list(self._pending.values())

    # -- output guarding ---------------------------------------------------

    def guard_output(self, text: str) -> tuple[str, list[dict]]:
        """Flag instruction-like content in tool output.

        The text is returned unchanged: it is the caller's data. What changes
        is that findings travel with it, so a reader can see that the content
        tried to act like an instruction.
        """
        findings = scan_untrusted(text, self.policy)
        return text, [finding.model_dump(mode="json") for finding in findings]

    def check_instruction_source(self, source: str) -> None:
        assert_instruction_source(source)
