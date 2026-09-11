"""Shell risk grading.

docs/safety.md grades shell work LOW / MEDIUM / HIGH and requires HIGH to be
confirmed by a human. The grader is deliberately conservative:

* the command is split on the shell operators (; && || | newline) and every
  segment is graded, because \"ls && rm -rf /\" must not pass as \"ls\"
* an unrecognised command is HIGH, not LOW (deny-by-default)
* destructive patterns and sensitive-file references are DENIED outright
* a path outside the project raises the grade to HIGH
"""

from __future__ import annotations

import re
import shlex

from .models import ShellAssessment
from .paths import FilesystemPolicy
from .policy import SafetyPolicy

SEGMENT_SPLIT = re.compile(r"(?:&&|\|\||;|\||\n|\r)")

# Commands that do not touch anything by themselves.
INERT_COMMANDS = {"echo", "pwd", "cd", "true", "false", ":", "whoami", "date", "which", "where"}


def _tokens(segment: str) -> list[str]:
    text = segment.strip()
    if not text:
        return []
    try:
        return [part.strip("\"'") for part in shlex.split(text, posix=False)]
    except ValueError:
        return text.split()


def _first_word(segment: str) -> str:
    text = segment.strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, posix=False)
    except ValueError:
        parts = text.split()
    for part in parts:
        token = part.strip("\"'")
        if token and not token.startswith("-"):
            return token.lower()
    return ""


class ShellGrader:
    def __init__(self, policy: SafetyPolicy, filesystem: FilesystemPolicy) -> None:
        self.policy = policy
        self.filesystem = filesystem

    # -- one segment -------------------------------------------------------

    def _grade(self, segment: str) -> tuple[str, list[str]]:
        """Grade a single command segment: low / medium / high."""
        word = _first_word(segment)
        if not word:
            return "low", []

        tokens = _tokens(segment)
        subcommand = ""
        for token in tokens[1:]:
            if not token.startswith("-"):
                subcommand = token.lower()
                break
            # a flag can itself be the dangerous thing (python -c, node -e)
            if token.lower() in self._all_subcommands(word):
                subcommand = token.lower()
                break

        reasons: list[str] = []

        if word in self.policy.high_risk_commands:
            return "high", ["high-risk command: " + word]

        # a shell inside a shell hides what actually runs
        if word in {"bash", "sh", "zsh", "powershell", "pwsh", "cmd"} and any(
            token == "-c" for token in tokens
        ):
            return "high", ["nested shell invocation: " + word]

        dangerous = self.policy.high_risk_subcommands.get(word, set())
        if subcommand and subcommand in dangerous:
            return "high", ["high-risk subcommand: " + word + " " + subcommand]

        read_only = self.policy.read_only_subcommands.get(word)
        if read_only is not None:
            if subcommand in read_only:
                return "low", ["read-only invocation: " + word + " " + subcommand]
            return "high", ["subcommand not on the read-only list: " + word + " " + (subcommand or "?")]

        if word in INERT_COMMANDS or word in self.policy.low_risk_commands:
            return "low", []
        if word in self.policy.dev_commands:
            return "medium", ["development command: " + word]
        return "high", ["unrecognised command, treated as high risk: " + word]

    def _all_subcommands(self, word: str) -> set[str]:
        return self.policy.high_risk_subcommands.get(word, set()) | self.policy.read_only_subcommands.get(word, set())

    def assess(self, command: str, cwd: str | None = None) -> ShellAssessment:
        from pathlib import Path

        base = Path(cwd) if cwd else None
        reasons: list[str] = []
        segments = [s for s in (part.strip() for part in SEGMENT_SPLIT.split(command)) if s]

        risk = "low"
        deny = False
        deny_reason = ""

        # Destructive regardless of the verb.
        for pattern in self.policy.destructive_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                deny = True
                deny_reason = "matches a destructive pattern: " + pattern
                reasons.append(deny_reason)
                break

        sensitive = self.filesystem.sensitive_reference(command)
        if sensitive is not None:
            deny = True
            deny_reason = "the command " + sensitive
            reasons.append(deny_reason)

        outside = self.filesystem.outside_paths_in(command, base)
        if outside:
            risk = "high"
            reasons.append(
                "touches a path outside the project: " + ", ".join(outside[:3])
            )

        for segment in segments:
            segment_risk, segment_reasons = self._grade(segment)
            if segment_risk == "high" or risk == "high":
                risk = "high"
            elif segment_risk == "medium" or risk == "medium":
                risk = "medium"
            else:
                risk = "low"
            reasons.extend(segment_reasons)

        if not segments:
            risk = "high"
            reasons.append("empty command")

        # A denied command is never a low-risk one, whatever its verb.
        if deny:
            risk = "high"

        if not reasons:
            reasons.append("read-only project command")

        return ShellAssessment(
            risk=risk,  # type: ignore[arg-type]
            reasons=reasons,
            segments=segments,
            deny=deny,
            deny_reason=deny_reason,
            outside_paths=outside,
            sensitive_reference=sensitive,
        )
