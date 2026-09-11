"""ToolCallParser: turn model output into validated ToolCall objects.

The parser is deliberately forgiving about PACKAGING and strict about
CONTENT. Models wrap the same call in a bare JSON object, a fenced block, a
JSON5 literal, an array, or prose; all of those must yield the same call. What
they may not do is invent a tool or omit an argument.

Shapes accepted for one call:

    {"name": "read_file", "arguments": {"path": "a.txt"}}
    {"tool": "read_file", "args": {...}}
    {"tool_call": {"name": ..., "parameters": {...}}}
    {"type": "tool_call", "name": ..., "input": {...}}
    {"function": {"name": ..., "arguments": "{\\"path\\": \\"a.txt\\"}"}}
    {"tool_calls": [ ...any of the above... ]}
    [ ...any of the above... ]

Every failure is reported as a ParseIssue with a stable code, the character
offset when one exists, and a repair hint, so a caller can feed the problem
back to the model instead of guessing (see ParseRetryPolicy).
"""

from __future__ import annotations

import json
from typing import Any

from .json5 import Json5Error
from .json5 import loads as json5_loads
from .models import (
    CallFormat,
    ParseIssue,
    ParseOutcome,
    ToolCall,
)

DEFAULT_MAX_CALLS = 16

# Keys that may carry the tool name, in the order we trust them.
NAME_KEYS = ("name", "tool", "tool_name", "toolName", "function")
# Keys that may carry the arguments.
ARGUMENT_KEYS = ("arguments", "parameters", "args", "input", "params", "arguments_json")


# ---------------------------------------------------------------------------
# bracket matching
# ---------------------------------------------------------------------------


def scan_balanced(text: str) -> tuple[list[tuple[int, int]], int | None]:
    """Find balanced {...} / [...] spans at the top level.

    Returns (spans, unbalanced_index). The index points at the opening bracket
    that never closed, which is what a repair hint needs to mention.
    """
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    start: int | None = None
    in_string: str | None = None
    escaped = False

    for position, char in enumerate(text):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in "\"'":
            in_string = char
            continue
        if char in "{[":
            if not stack:
                start = position
            stack.append((char, position))
            continue
        if char in "}]":
            if not stack:
                # A stray closer: the preceding span (if any) is malformed.
                return spans, position
            opener, opener_position = stack.pop()
            if (opener, char) not in (("{", "}"), ("[", "]")):
                return spans, opener_position
            if not stack and start is not None:
                spans.append((start, position + 1))
                start = None

    if stack:
        return spans, stack[0][1]
    if in_string is not None:
        return spans, len(text) - 1
    return spans, None


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _try_parse(payload: str) -> tuple[Any, CallFormat, ParseIssue | None]:
    """Parse one payload as JSON, then JSON5. Returns (value, format, issue)."""
    try:
        return json.loads(payload), "json", None
    except json.JSONDecodeError as json_error:
        try:
            return json5_loads(payload), "json5", None
        except Json5Error as json5_error:
            return None, "none", ParseIssue(
                code="invalid_json",
                message=(
                    "the payload is neither valid JSON nor valid JSON5: "
                    + json5_error.message
                ),
                position=json5_error.index,
                snippet=json5_error.snippet,
                repair_hint=(
                    "re-emit the call as a single strict JSON object, for example "
                    '{"name": "read_file", "arguments": {"path": "a.txt"}}'
                ),
            )


def _fenced_blocks(text: str) -> list[tuple[str, str, CallFormat]]:
    """Extract fenced code blocks as (payload, language, format)."""
    blocks: list[tuple[str, str, CallFormat]] = []
    cursor = 0
    while True:
        opening = text.find("```", cursor)
        if opening == -1:
            return blocks
        line_end = text.find("\n", opening)
        if line_end == -1:
            return blocks
        language = text[opening + 3 : line_end].strip().lower()
        closing = text.find("```", line_end + 1)
        if closing == -1:
            # Unterminated fence: treat the remainder as the payload.
            payload = text[line_end + 1 :]
            blocks.append((payload, language, "code_fence"))
            return blocks
        payload = text[line_end + 1 : closing]
        cursor = closing + 3
        if language in ("json5",):
            blocks.append((payload, language, "fenced_json5"))
        elif language in ("json", "tool", "tool_call", "toolcall", "javascript", "js", ""):
            blocks.append((payload, language, "code_fence"))
        else:
            blocks.append((payload, language, "code_fence"))


def _coerce_arguments(value: Any) -> tuple[dict | None, ParseIssue | None]:
    """Arguments may arrive as an object or as a JSON/JSON5 string."""
    if value is None:
        return {}, None
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}, None
        parsed, _format, issue = _try_parse(text)
        if issue is not None:
            return None, issue.model_copy(
                update={
                    "code": "invalid_arguments",
                    "message": "the arguments string is not valid JSON: " + issue.message,
                    "repair_hint": (
                        "send the arguments as a JSON object, not as a broken string"
                    ),
                }
            )
        if isinstance(parsed, dict):
            return parsed, None
        return None, ParseIssue(
            code="invalid_arguments",
            message="the arguments value is not an object",
            repair_hint="arguments must be a JSON object of named parameters",
        )
    return None, ParseIssue(
        code="invalid_arguments",
        message="the arguments value has an unsupported type",
        repair_hint="arguments must be a JSON object of named parameters",
    )


def _extract_name(record: dict) -> tuple[str | None, ParseIssue | None]:
    for key in NAME_KEYS:
        if key not in record:
            continue
        value = record[key]
        if isinstance(value, str) and value.strip():
            return value.strip(), None
        if isinstance(value, dict):
            inner = value.get("name")
            if isinstance(inner, str) and inner.strip():
                # OpenAI-style {"function": {"name":..., "arguments":...}}
                return inner.strip(), None
    return None, ParseIssue(
        code="missing_name",
        message="the call has no tool name",
        repair_hint=(
            'include a "name" field naming the tool, for example '
            '{"name": "list_dir", "arguments": {}}'
        ),
    )


def _extract_arguments(record: dict) -> tuple[dict | None, ParseIssue | None]:
    function_block = record.get("function")
    if isinstance(function_block, dict) and "arguments" in function_block:
        return _coerce_arguments(function_block.get("arguments"))
    for key in ARGUMENT_KEYS:
        if key in record:
            return _coerce_arguments(record[key])
    return None, ParseIssue(
        code="missing_arguments",
        message="the call has no arguments object",
        repair_hint='include an "arguments" object (it may be empty: {})',
    )


def _record_to_calls(
    record: Any,
    fmt: CallFormat,
    raw: str,
    known_tools: set[str] | None,
    issues: list[ParseIssue],
    start_index: int,
) -> list[ToolCall]:
    calls: list[ToolCall] = []

    if isinstance(record, list):
        for item in record:
            calls.extend(
                _record_to_calls(item, fmt, raw, known_tools, issues, start_index + len(calls))
            )
        return calls

    if not isinstance(record, dict):
        issues.append(
            ParseIssue(
                code="not_an_object",
                message="a tool call must be a JSON object",
                repair_hint='wrap the call as {"name": ..., "arguments": {...}}',
            )
        )
        return calls

    # A wrapper may hold a list of calls.
    for wrapper_key in ("tool_calls", "toolCalls", "calls"):
        if isinstance(record.get(wrapper_key), list):
            for item in record[wrapper_key]:
                calls.extend(
                    _record_to_calls(
                        item, fmt, raw, known_tools, issues, start_index + len(calls)
                    )
                )
            return calls
    if isinstance(record.get("tool_call"), dict):
        return _record_to_calls(
            record["tool_call"], fmt, raw, known_tools, issues, start_index
        )

    name, name_issue = _extract_name(record)
    if name_issue is not None:
        issues.append(name_issue)
        return calls

    arguments, argument_issue = _extract_arguments(record)
    if argument_issue is not None:
        issues.append(argument_issue)
        return calls

    if known_tools is not None and name not in known_tools:
        issues.append(
            ParseIssue(
                code="unknown_tool",
                message="unknown tool " + repr(name),
                repair_hint=(
                    "use one of: " + ", ".join(sorted(known_tools))
                ),
            )
        )
        return calls

    calls.append(
        ToolCall(
            id="call-" + str(start_index + len(calls) + 1),
            name=name,
            arguments=arguments or {},
            raw=raw,
            format=fmt,
            index=start_index + len(calls),
        )
    )
    return calls


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def parse_tool_calls(
    text: str,
    known_tools: set[str] | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> ParseOutcome:
    """Parse model output into tool calls, reporting every problem found."""
    raw = text or ""
    if not raw.strip():
        return ParseOutcome(
            format="none",
            raw=raw,
            issues=[
                ParseIssue(
                    code="empty_input",
                    message="there was no model output to parse",
                    repair_hint="emit a tool call object",
                )
            ],
        )

    issues: list[ParseIssue] = []
    calls: list[ToolCall] = []
    used_format: CallFormat = "none"
    saw_structure = False

    blocks = _fenced_blocks(raw)
    candidates: list[tuple[str, CallFormat]] = [
        (payload, fmt) for payload, _language, fmt in blocks
    ]
    if not candidates:
        candidates.append((raw, "json"))

    for payload, fmt in candidates:
        value, parsed_format, issue = _try_parse(payload)

        if issue is not None:
            # Bracket matching: recover the balanced objects from mixed text,
            # and explain an unbalanced opener precisely when there is one.
            spans, unbalanced_at = scan_balanced(payload)
            if spans or unbalanced_at is not None:
                saw_structure = True
            recovered = False
            for start, end in spans:
                inner_value, inner_format, inner_issue = _try_parse(payload[start:end])
                if inner_issue is None and isinstance(inner_value, (dict, list)):
                    recovered = True
                    found = _record_to_calls(
                        inner_value,
                        inner_format if inner_format != "none" else fmt,
                        payload[start:end],
                        known_tools,
                        issues,
                        len(calls),
                    )
                    calls.extend(found)
                    used_format = used_format if used_format != "none" else inner_format
            if recovered:
                if used_format == "none":
                    used_format = "embedded"
                continue
            if unbalanced_at is not None:
                issues.append(
                    ParseIssue(
                        code="unbalanced_brackets",
                        message=(
                            "a bracket opened at offset "
                            + str(unbalanced_at)
                            + " is never closed"
                        ),
                        position=unbalanced_at,
                        snippet=issue.snippet,
                        repair_hint=(
                            "close every brace and bracket, and re-emit the complete object"
                        ),
                    )
                )
            else:
                issues.append(issue)
            continue

        found = _record_to_calls(
            value, parsed_format, payload, known_tools, issues, len(calls)
        )
        if found:
            calls.extend(found)
            if used_format == "none":
                used_format = fmt if fmt != "json" else parsed_format

    if len(calls) > max_calls:
        issues.append(
            ParseIssue(
                code="too_many_calls",
                message="more than " + str(max_calls) + " tool calls in one turn",
                repair_hint="split the work across turns",
            )
        )
        calls = calls[:max_calls]

    no_call_issue = ParseIssue(
        code="no_tool_call",
        message="no tool call was found in the output",
        repair_hint='emit {"name": "<tool>", "arguments": {...}}',
    )
    if not calls and not issues:
        issues.append(no_call_issue)
    elif (
        not calls
        and not saw_structure
        and all(issue.code == "invalid_json" for issue in issues)
    ):
        # Nothing parses and there is no JSON structure anywhere: the model
        # simply did not emit a tool call, and "invalid JSON" would mislead it
        # into hunting for a syntax error that does not exist.
        issues = [no_call_issue]

    for position, call in enumerate(calls):
        calls[position] = call.model_copy(update={"index": position})

    return ParseOutcome(calls=calls, issues=issues, format=used_format, raw=raw)


def repair_prompt(outcome: ParseOutcome) -> str:
    """Turn parse issues into an instruction the model can act on."""
    lines = ["Your tool call could not be parsed. Problems:"]
    for issue in outcome.issues:
        location = "" if issue.position is None else " (offset " + str(issue.position) + ")"
        lines.append("- " + issue.code + location + ": " + issue.message)
        if issue.repair_hint:
            lines.append("  fix: " + issue.repair_hint)
        if issue.snippet:
            lines.append("  near: " + issue.snippet)
    lines.append("Re-emit the complete tool call as one strict JSON object.")
    return "\n".join(lines)


class ParseRetryPolicy:
    """Bounded retry bookkeeping for unparsable tool calls.

    M3 owns the budget and the repair text; the loop that actually re-asks the
    model belongs to a later milestone, so this class stays pure.
    """

    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.attempts = 0
        self.history: list[ParseOutcome] = []

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def record(self, outcome: ParseOutcome) -> bool:
        """Record one parse attempt; returns True when another try is allowed."""
        self.history.append(outcome)
        if outcome.ok:
            return False
        self.attempts += 1
        return not self.exhausted

    def instruction(self) -> str:
        if not self.history:
            return ""
        latest = self.history[-1]
        header = (
            "Attempt " + str(self.attempts) + " of " + str(self.max_attempts) + ". "
            if self.attempts
            else ""
        )
        return header + repair_prompt(latest)
