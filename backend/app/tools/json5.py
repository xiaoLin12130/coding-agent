"""Minimal JSON5 reader.

M3 requires the ToolCallParser to accept JSON5 (unquoted keys, single quotes,
trailing commas, comments). Pulling in a dependency for that is unnecessary
here, so this is a small hand-written reader covering the subset an LLM
actually emits:

* objects and arrays, with trailing commas
* single- or double-quoted strings (with the usual escapes and a
  backslash-newline continuation)
* unquoted identifier keys
* numbers: leading sign, hex, decimals, exponents
* // line comments and /* block */ comments
* true / false / null

Deliberately NOT supported: NaN, Infinity, and bullet-point "keys". Anything
this reader cannot parse raises Json5Error, which carries the character offset
so the caller can produce a structured, repairable error.
"""

from __future__ import annotations

import re
from typing import Any

WHITESPACE = " \t\r\n\f\v\u00a0\ufeff"
IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


class Json5Error(ValueError):
    """A syntax error, carrying enough context to repair the input."""

    def __init__(self, message: str, index: int = 0, text: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.index = index
        self.text = text

    @property
    def snippet(self) -> str:
        if not self.text:
            return ""
        start = max(self.index - 30, 0)
        end = min(self.index + 30, len(self.text))
        return ("..." if start > 0 else "") + self.text[start:end] + (
            "..." if end < len(self.text) else ""
        )


_SIMPLE_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # -- helpers -----------------------------------------------------------

    def fail(self, message: str) -> None:
        raise Json5Error(message, self.pos, self.text)

    def skip_trivia(self) -> None:
        text = self.text
        size = len(text)
        while self.pos < size:
            char = text[self.pos]
            if char in WHITESPACE:
                self.pos += 1
                continue
            if char == "/" and self.pos + 1 < size:
                following = text[self.pos + 1]
                if following == "/":
                    self.pos += 2
                    while self.pos < size and text[self.pos] not in "\r\n":
                        self.pos += 1
                    continue
                if following == "*":
                    end = text.find("*/", self.pos + 2)
                    if end == -1:
                        self.fail("unterminated block comment")
                    self.pos = end + 2
                    continue
            break

    def peek_identifier(self) -> str:
        match = IDENTIFIER.match(self.text, self.pos)
        return match.group(0) if match else ""

    # -- values ------------------------------------------------------------

    def parse_value(self) -> Any:
        self.skip_trivia()
        if self.pos >= len(self.text):
            self.fail("unexpected end of input")
        char = self.text[self.pos]

        if char == "{":
            return self.parse_object()
        if char == "[":
            return self.parse_array()
        if char in "\"'":
            return self.parse_string()
        if char in "+-." or char.isdigit():
            return self.parse_number()

        word = self.peek_identifier()
        if word == "true":
            self.pos += 4
            return True
        if word == "false":
            self.pos += 5
            return False
        if word == "null":
            self.pos += 4
            return None
        self.fail("unexpected character " + repr(char))
        return None  # unreachable

    def parse_object(self) -> dict:
        result: dict = {}
        self.pos += 1  # consume {
        self.skip_trivia()
        if self.pos < len(self.text) and self.text[self.pos] == "}":
            self.pos += 1
            return result

        while True:
            self.skip_trivia()
            if self.pos >= len(self.text):
                self.fail("unterminated object")
            char = self.text[self.pos]
            if char in "\"'":
                key = self.parse_string()
            else:
                match = IDENTIFIER.match(self.text, self.pos)
                if not match:
                    self.fail("expected a property name")
                key = match.group(0)
                self.pos = match.end()

            self.skip_trivia()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                self.fail("expected ':' after property " + repr(key))
            self.pos += 1

            result[str(key)] = self.parse_value()
            self.skip_trivia()
            if self.pos >= len(self.text):
                self.fail("unterminated object")
            char = self.text[self.pos]
            if char == ",":
                self.pos += 1
                self.skip_trivia()
                if self.pos < len(self.text) and self.text[self.pos] == "}":
                    self.pos += 1
                    return result
                continue
            if char == "}":
                self.pos += 1
                return result
            self.fail("expected ',' or '}' in object")

    def parse_array(self) -> list:
        result: list = []
        self.pos += 1  # consume [
        self.skip_trivia()
        if self.pos < len(self.text) and self.text[self.pos] == "]":
            self.pos += 1
            return result

        while True:
            result.append(self.parse_value())
            self.skip_trivia()
            if self.pos >= len(self.text):
                self.fail("unterminated array")
            char = self.text[self.pos]
            if char == ",":
                self.pos += 1
                self.skip_trivia()
                if self.pos < len(self.text) and self.text[self.pos] == "]":
                    self.pos += 1
                    return result
                continue
            if char == "]":
                self.pos += 1
                return result
            self.fail("expected ',' or ']' in array")

    def parse_string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        pieces: list[str] = []
        size = len(self.text)
        while True:
            if self.pos >= size:
                self.fail("unterminated string")
            char = self.text[self.pos]
            if char == quote:
                self.pos += 1
                return "".join(pieces)
            if char == "\\":
                self.pos += 1
                if self.pos >= size:
                    self.fail("unterminated escape sequence")
                escape = self.text[self.pos]
                if escape == "u":
                    hex_digits = self.text[self.pos + 1 : self.pos + 5]
                    if len(hex_digits) != 4:
                        self.fail("incomplete unicode escape")
                    try:
                        pieces.append(chr(int(hex_digits, 16)))
                    except ValueError:
                        self.fail("invalid unicode escape " + repr(hex_digits))
                    self.pos += 5
                    continue
                if escape in "\r\n":
                    # line continuation
                    self.pos += 1
                    if escape == "\r" and self.pos < size and self.text[self.pos] == "\n":
                        self.pos += 1
                    continue
                pieces.append(_SIMPLE_ESCAPES.get(escape, escape))
                self.pos += 1
                continue
            if char in "\r\n":
                self.fail("unescaped newline in string")
            pieces.append(char)
            self.pos += 1

    def parse_number(self) -> Any:
        start = self.pos
        size = len(self.text)
        if self.pos < size and self.text[self.pos] in "+-":
            self.pos += 1
        if self.text.startswith("0x", self.pos) or self.text.startswith("0X", self.pos):
            self.pos += 2
            digits_start = self.pos
            while self.pos < size and self.text[self.pos] in "0123456789abcdefABCDEF":
                self.pos += 1
            if self.pos == digits_start:
                self.fail("invalid hexadecimal number")
            return int(self.text[digits_start : self.pos], 16) * (
                -1 if self.text[start] == "-" else 1
            )
        while self.pos < size and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos < size and self.text[self.pos] == ".":
            self.pos += 1
            while self.pos < size and self.text[self.pos].isdigit():
                self.pos += 1
        if self.pos < size and self.text[self.pos] in "eE":
            self.pos += 1
            if self.pos < size and self.text[self.pos] in "+-":
                self.pos += 1
            while self.pos < size and self.text[self.pos].isdigit():
                self.pos += 1
        raw = self.text[start : self.pos]
        if raw in ("", "+", "-", "."):
            self.fail("invalid number " + repr(raw))
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            self.fail("invalid number " + repr(raw))
        return None  # unreachable


def loads(text: str) -> Any:
    """Parse one JSON5 value; raises Json5Error with the failing offset."""
    reader = _Reader(text)
    value = reader.parse_value()
    reader.skip_trivia()
    if reader.pos != len(reader.text):
        reader.fail("trailing content after the JSON5 value")
    return value


def is_probably_json5(text: str) -> bool:
    """Cheap pre-check used to pick a repair strategy."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] not in "{[\"'":
        return False
    try:
        loads(stripped)
    except Json5Error:
        return False
    return True
