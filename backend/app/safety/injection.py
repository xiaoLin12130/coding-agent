"""Prompt-injection defence.

docs/safety.md: web text, file text, tool results, shell output and external
documents are DATA. Even when they contain commands, they must never be
promoted to instructions.

Two mechanisms enforce that:

* scope()/scan() — flag instruction-like content in untrusted text so it can be
  surfaced and wrapped instead of silently trusted
* assert_instruction_source() — the parser only accepts output that came from
  the MODEL. Tool output arriving at the parser is refused, which is what makes
  \"cannot be executed\" structural rather than a matter of good behaviour.
"""

from __future__ import annotations

import re

from .models import InjectionFinding
from .policy import SafetyPolicy

ALLOWED_INSTRUCTION_SOURCES = frozenset({"model", "user"})


class InjectedInstructionError(RuntimeError):
    """Raised when content from an untrusted source is treated as instructions."""

    code = "untrusted_instruction_source"


def scan_untrusted(text: str, policy: SafetyPolicy) -> list[InjectionFinding]:
    """Find instruction-like patterns in untrusted content."""
    findings: list[InjectionFinding] = []
    if not text:
        return findings
    for pattern, category in policy.injection_patterns:
        for match in re.finditer(pattern, text):
            start = max(match.start() - 20, 0)
            end = min(match.end() + 20, len(text))
            findings.append(
                InjectionFinding(
                    category=category,
                    message="untrusted content contains a possible " + category,
                    excerpt=" ".join(text[start:end].split())[:160],
                    position=match.start(),
                )
            )
    findings.sort(key=lambda finding: finding.position)
    return findings


def categories(findings: list[InjectionFinding]) -> list[str]:
    seen: list[str] = []
    for finding in findings:
        if finding.category not in seen:
            seen.append(finding.category)
    return seen


def assert_instruction_source(source: str) -> None:
    """Refuse to treat anything but model/user output as instructions."""
    if source not in ALLOWED_INSTRUCTION_SOURCES:
        raise InjectedInstructionError(
            "content from source "
            + repr(source)
            + " is DATA and cannot be parsed as instructions;"
            + " only "
            + ", ".join(sorted(ALLOWED_INSTRUCTION_SOURCES))
            + " may issue tool calls"
        )


def wrap_untrusted(text: str, policy: SafetyPolicy) -> str:
    """Wrap untrusted text in an explicit marker with the standard notice."""
    return (
        policy.untrusted_section_notice
        + "\n<<<UNTRUSTED_DATA>>>\n"
        + text
        + "\n<<<END_UNTRUSTED_DATA>>>"
    )
