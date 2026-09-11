"""ToolCallParser golden set (docs/testing.md).

Covers: standard JSON, markdown code fence, JSON5, multiple tool calls,
bracket errors, missing fields, invalid JSON, mixed text — plus the retry
policy that turns a structured error back into an instruction.
"""

from __future__ import annotations

import json

import pytest

from app.tools.json5 import Json5Error, is_probably_json5, loads as json5_loads
from app.tools.parser import (
    ParseRetryPolicy,
    parse_tool_calls,
    repair_prompt,
    scan_balanced,
)

TOOLS = {"read_file", "write_file", "list_dir", "run_shell", "search"}

FENCE = chr(96) * 3


# ---------------------------------------------------------------------------
# golden set: shapes that MUST parse
# ---------------------------------------------------------------------------

GOLDEN_OK = [
    (
        "standard json",
        '{"name": "read_file", "arguments": {"path": "a.txt"}}',
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "standard json with whitespace",
        '  \n  {  "name" : "read_file" ,  "arguments" : { "path" : "a.txt" } }  \n ',
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "markdown code fence",
        "Sure, here is the call:\n" + FENCE + 'json\n{"name": "list_dir", "arguments": {"path": "."}}\n' + FENCE,
        [("list_dir", {"path": "."})],
    ),
    (
        "code fence without a language",
        FENCE + '\n{"name": "list_dir", "arguments": {}}\n' + FENCE,
        [("list_dir", {})],
    ),
    (
        "json5 unquoted keys and single quotes",
        "{name: 'read_file', arguments: {path: 'a.txt'}}",
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "json5 trailing commas and comments",
        "// pick a file\n{name: 'read_file', arguments: {path: 'a.txt',}, /* done */}",
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "json5 alternate key names",
        "{tool: 'list_dir', args: {path: '.', depth: 2}}",
        [("list_dir", {"path": ".", "depth": 2})],
    ),
    (
        "multiple calls in an array",
        '[{"name": "read_file", "arguments": {"path": "a"}},'
        ' {"name": "read_file", "arguments": {"path": "b"}}]',
        [("read_file", {"path": "a"}), ("read_file", {"path": "b"})],
    ),
    (
        "multiple calls under a wrapper",
        '{"tool_calls": [{"name": "list_dir", "arguments": {}},'
        ' {"name": "read_file", "arguments": {"path": "x"}}]}',
        [("list_dir", {}), ("read_file", {"path": "x"})],
    ),
    (
        "multiple concatenated objects",
        '{"name": "list_dir", "arguments": {}}{"name": "search", "arguments": {"pattern": "x"}}',
        [("list_dir", {}), ("search", {"pattern": "x"})],
    ),
    (
        "nested tool_call wrapper",
        '{"tool_call": {"name": "search", "parameters": {"pattern": "todo"}}}',
        [("search", {"pattern": "todo"})],
    ),
    (
        "openai style function block",
        '{"type": "tool_call", "function": {"name": "read_file", '
        '"arguments": "{\\"path\\": \\"a.txt\\"}"}}',
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "alias keys arguments/parameters/args/input",
        '{"tool_name": "read_file", "parameters": {"path": "p"}}',
        [("read_file", {"path": "p"})],
    ),
    (
        "mixed text around the call",
        'I will read the file now. {"name": "read_file", "arguments": {"path": "a.txt"}} '
        "That should tell us what we need.",
        [("read_file", {"path": "a.txt"})],
    ),
    (
        "mixed text with a fenced block",
        "Let me look.\n" + FENCE + '\n{name: "list_dir", arguments: {}}\n' + FENCE + "\nDone.",
        [("list_dir", {})],
    ),
    (
        "unicode content survives",
        '{"name": "write_file", "arguments": {"path": "a.txt", "content": "中文内容 ✅"}}',
        [("write_file", {"path": "a.txt", "content": "中文内容 ✅"})],
    ),
]


@pytest.mark.parametrize("label,text,expected", GOLDEN_OK, ids=[c[0] for c in GOLDEN_OK])
def test_golden_parses(label: str, text: str, expected: list) -> None:
    outcome = parse_tool_calls(text, TOOLS)

    assert outcome.ok is True, (label, outcome.codes(), outcome.issues)
    assert [(c.name, c.arguments) for c in outcome.calls] == expected
    assert all(call.id for call in outcome.calls)


@pytest.mark.parametrize("label,text,expected", GOLDEN_OK, ids=[c[0] for c in GOLDEN_OK])
def test_golden_call_indices_are_sequential(label: str, text: str, expected: list) -> None:
    outcome = parse_tool_calls(text, TOOLS)

    assert [call.index for call in outcome.calls] == list(range(len(expected)))


# ---------------------------------------------------------------------------
# golden set: shapes that MUST fail, with a stable code
# ---------------------------------------------------------------------------

GOLDEN_BAD = [
    ("empty input", "", "empty_input"),
    ("whitespace only", "   \n  ", "empty_input"),
    ("plain prose, no call", "I would rather you read the file yourself.", "no_tool_call"),
    ("missing name", '{"arguments": {"path": "a.txt"}}', "missing_name"),
    ("blank name", '{"name": "   ", "arguments": {}}', "missing_name"),
    ("unknown tool", '{"name": "rm_rf", "arguments": {}}', "unknown_tool"),
    ("not an object", '"just a string"', "not_an_object"),
    ("invalid json body", '{"name": "read_file", "arguments": {path: }}', "invalid_json"),
    (
        "unbalanced braces",
        '{"name": "read_file", "arguments": {"path": "a.txt"}',
        "unbalanced_brackets",
    ),
    (
        "unbalanced nested array",
        '{"name": "search", "arguments": {"pattern": "x", "tags": ["a", "b"}}',
        "unbalanced_brackets",
    ),
    ("garbage", "{oops}", "invalid_json"),
]


@pytest.mark.parametrize("label,text,code", GOLDEN_BAD, ids=[c[0] for c in GOLDEN_BAD])
def test_golden_failures_report_the_expected_code(
    label: str, text: str, code: str
) -> None:
    outcome = parse_tool_calls(text, TOOLS)

    assert outcome.ok is False, label
    assert code in outcome.codes(), (label, outcome.codes())
    assert outcome.issues[0].repair_hint, "every failure must be repairable"


def test_missing_arguments_is_reported() -> None:
    outcome = parse_tool_calls('{"name": "read_file"}', TOOLS)
    assert outcome.codes() == ["missing_arguments"]


def test_arguments_as_a_broken_string_is_reported() -> None:
    outcome = parse_tool_calls(
        '{"name": "read_file", "arguments": "{path: }"}', TOOLS
    )
    assert outcome.codes() == ["invalid_arguments"]


def test_arguments_of_the_wrong_type_is_reported() -> None:
    outcome = parse_tool_calls('{"name": "read_file", "arguments": 42}', TOOLS)
    assert outcome.codes() == ["invalid_arguments"]


def test_unbalanced_error_points_at_the_opener() -> None:
    text = '{"name": "read_file", "arguments": {"path": "a.txt"}'
    outcome = parse_tool_calls(text, TOOLS)

    issue = outcome.issues[0]
    assert issue.code == "unbalanced_brackets"
    assert issue.position == 0, "the unclosed outer brace is at offset 0"
    assert issue.snippet


def test_max_calls_is_enforced() -> None:
    text = json.dumps(
        [{"name": "list_dir", "arguments": {}} for _ in range(5)]
    )
    outcome = parse_tool_calls(text, TOOLS, max_calls=2)

    assert len(outcome.calls) == 2
    assert "too_many_calls" in outcome.codes()


def test_partial_success_is_reported_as_partial() -> None:
    text = (
        '[{"name": "list_dir", "arguments": {}},'
        ' {"name": "not_a_tool", "arguments": {}}]'
    )
    outcome = parse_tool_calls(text, TOOLS)

    assert outcome.partial is True
    assert [c.name for c in outcome.calls] == ["list_dir"]
    assert outcome.codes() == ["unknown_tool"]


def test_known_tools_is_optional() -> None:
    outcome = parse_tool_calls('{"name": "anything", "arguments": {}}')
    assert outcome.ok is True


def test_raw_output_is_preserved_for_debugging() -> None:
    text = '{"name": "list_dir", "arguments": {}}'
    assert parse_tool_calls(text, TOOLS).raw == text


def test_format_is_reported() -> None:
    assert parse_tool_calls('{"name": "list_dir", "arguments": {}}', TOOLS).format == "json"
    assert parse_tool_calls("{name: 'list_dir', arguments: {}}", TOOLS).format == "json5"
    assert (
        parse_tool_calls(FENCE + 'json\n{"name": "list_dir", "arguments": {}}\n' + FENCE, TOOLS).format
        == "code_fence"
    )


# ---------------------------------------------------------------------------
# bracket matching
# ---------------------------------------------------------------------------


def test_scan_balanced_finds_top_level_spans() -> None:
    text = 'x {"a": 1} y [2, 3] z'
    spans, unbalanced = scan_balanced(text)

    assert unbalanced is None
    assert len(spans) == 2
    assert text[spans[0][0] : spans[0][1]] == '{"a": 1}'
    assert text[spans[1][0] : spans[1][1]] == "[2, 3]"


def test_scan_balanced_reports_the_unclosed_opener() -> None:
    spans, unbalanced = scan_balanced('{"a": {"b": 1}')
    assert spans == []
    assert unbalanced == 0


def test_scan_balanced_ignores_brackets_inside_strings() -> None:
    text = '{"a": "}{"}'
    spans, unbalanced = scan_balanced(text)

    assert unbalanced is None
    assert len(spans) == 1
    # The braces inside the string must not close the object early.
    assert text[spans[0][0] : spans[0][1]] == text


def test_scan_balanced_ignores_escaped_quotes() -> None:
    spans, unbalanced = scan_balanced('{"a": "\\"} "}')
    assert unbalanced is None
    assert spans


def test_scan_balanced_handles_a_stray_closer() -> None:
    spans, unbalanced = scan_balanced("}")
    assert spans == []
    assert unbalanced == 0


# ---------------------------------------------------------------------------
# JSON5 reader
# ---------------------------------------------------------------------------


def test_json5_reads_the_supported_subset() -> None:
    value = json5_loads(
        "// comment\n{"
        "  a: [1, 2, 3,],"
        "  'b': 'text',"
        "  c: 0x1F,"
        "  d: -1.5e3,"
        "  e: true,"
        "  f: null,"
        "  /* block */ g: {nested: 'yes'},"
        "}"
    )

    assert value == {
        "a": [1, 2, 3],
        "b": "text",
        "c": 31,
        "d": -1500.0,
        "e": True,
        "f": None,
        "g": {"nested": "yes"},
    }


def test_json5_decodes_escapes() -> None:
    assert json5_loads('{"a": "line\\nbreak", "u": "\\u0041"}') == {
        "a": "line\nbreak",
        "u": "A",
    }


def test_json5_rejects_malformed_input_with_a_position() -> None:
    with pytest.raises(Json5Error) as excinfo:
        json5_loads("{a: }")

    assert excinfo.value.index > 0
    assert excinfo.value.snippet


def test_json5_rejects_unterminated_structures() -> None:
    for text in ("{a: 1", "[1, 2", "{a: 'x}", "/* open"):
        with pytest.raises(Json5Error):
            json5_loads(text)


def test_json5_rejects_trailing_content() -> None:
    with pytest.raises(Json5Error):
        json5_loads("{a: 1} extra")


def test_is_probably_json5() -> None:
    assert is_probably_json5("{a: 1}") is True
    assert is_probably_json5("plain text") is False
    assert is_probably_json5("") is False
    assert is_probably_json5("{broken") is False


# ---------------------------------------------------------------------------
# retry policy
# ---------------------------------------------------------------------------


def test_retry_policy_allows_two_retries_then_stops() -> None:
    policy = ParseRetryPolicy(max_attempts=3)
    bad = parse_tool_calls('{"name": "read_file", "arguments": {path: }}', TOOLS)

    assert policy.record(bad) is True
    assert policy.record(bad) is True
    assert policy.record(bad) is False
    assert policy.exhausted is True
    assert policy.attempts == 3


def test_retry_policy_stops_once_the_parse_succeeds() -> None:
    policy = ParseRetryPolicy(max_attempts=3)
    good = parse_tool_calls('{"name": "list_dir", "arguments": {}}', TOOLS)

    assert policy.record(good) is False
    assert policy.attempts == 0
    assert policy.exhausted is False


def test_retry_policy_requires_a_positive_budget() -> None:
    with pytest.raises(ValueError):
        ParseRetryPolicy(max_attempts=0)


def test_repair_prompt_names_the_problem_and_the_fix() -> None:
    outcome = parse_tool_calls('{"name": "nope", "arguments": {}}', TOOLS)
    prompt = repair_prompt(outcome)

    assert "unknown_tool" in prompt
    assert "fix:" in prompt
    assert "read_file" in prompt, "the hint should list the available tools"


def test_retry_instruction_is_prefixed_with_the_attempt_count() -> None:
    policy = ParseRetryPolicy(max_attempts=3)
    policy.record(parse_tool_calls("nothing here", TOOLS))

    instruction = policy.instruction()

    assert instruction.startswith("Attempt 1 of 3.")
    assert "no_tool_call" in instruction
