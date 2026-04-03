"""Executable-line detection for JavaScript and TypeScript source files."""

from __future__ import annotations

import re
from pathlib import Path

_source_lines_cache: dict[str, set[int]] = {}

_STRUCTURAL_LINE_RE = re.compile(r"^[{}()[\],;]+$")
_NON_EXECUTABLE_KEYWORDS = {"do", "else", "finally", "try"}
_DIRECTIVE_LINE_RE = re.compile(
    r"^(?:\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^'\\]*(?:\\.[^'\\]*)*');?$"
)
_TS_INTERFACE_START_RE = re.compile(
    r"^(?:export\s+)?(?:declare\s+)?(?:default\s+)?interface\b"
)
_TS_TYPE_START_RE = re.compile(r"^(?:export\s+)?(?:declare\s+)?type\b")
_TS_DECLARE_STATEMENT_RE = re.compile(
    r"^(?:export\s+)?declare\s+(?:const|let|var|function|class|enum|namespace|module)\b"
)
_TS_AS_CAST_CONTINUATION_RE = re.compile(r"^[)\]}]?\s*as\b")
_TS_AS_CAST_OBJECT_START_RE = re.compile(r"\bas\b.*[&|]\s*\{$")


def strip_js_comment_text(source: str) -> str:
    """Return *source* with comments removed while preserving line structure."""
    result: list[str] = []
    in_block_comment = False
    string_delimiter: str | None = None
    escaped = False

    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if in_block_comment:
            if char == "\n":
                result.append(char)
            elif char == "*" and next_char == "/":
                in_block_comment = False
                index += 1
            index += 1
            continue

        if string_delimiter is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_delimiter:
                string_delimiter = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            while index < len(source) and source[index] != "\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        if char in {'"', "'", "`"}:
            string_delimiter = char

        result.append(char)
        index += 1

    return "".join(result)


def is_executable_line(text: str) -> bool:
    """Return True when a stripped JS/TS source line likely contains code."""
    if not text:
        return False
    if _STRUCTURAL_LINE_RE.fullmatch(text):
        return False

    normalized = text.strip("{}();,[] ")
    if not normalized:
        return False
    if normalized in _NON_EXECUTABLE_KEYWORDS:
        return False
    return True


def _delimiter_balance(text: str) -> int:
    """Return a coarse delimiter balance for multiline TS type constructs."""
    balance = 0
    for char in text:
        if char in "{[(<":
            balance += 1
        elif char in ")]>}":
            balance -= 1
    return balance


def _starts_ts_interface(text: str) -> bool:
    return bool(_TS_INTERFACE_START_RE.match(text))


def _starts_ts_type_alias(text: str) -> bool:
    return bool(_TS_TYPE_START_RE.match(text))


def _is_ts_declare_statement(text: str) -> bool:
    return bool(_TS_DECLARE_STATEMENT_RE.match(text))


def _is_directive_prologue_line(text: str) -> bool:
    return bool(_DIRECTIVE_LINE_RE.fullmatch(text))


def _is_ts_as_cast_continuation(text: str) -> bool:
    return bool(_TS_AS_CAST_CONTINUATION_RE.match(text))


def _starts_ts_as_cast_object_literal(text: str) -> bool:
    return bool(_TS_AS_CAST_OBJECT_START_RE.search(text))


def _type_alias_continues(text: str, balance: int) -> bool:
    if balance > 0:
        return True
    if text.endswith(";"):
        return False
    if text.startswith(("|", "&")):
        return True
    return text.endswith(("=", "|", "&", ",", "{", "(", "[", "<"))


def _template_state_after_line(
    text: str, in_template_literal: bool, template_expr_depth: int
) -> tuple[bool, int]:
    """Return template-literal state after scanning one line of source text."""
    in_string: str | None = None
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if in_template_literal and template_expr_depth == 0:
            if char == "`":
                in_template_literal = False
            elif char == "$" and next_char == "{":
                template_expr_depth = 1
                index += 1
            index += 1
            continue

        if char in {'"', "'"}:
            in_string = char
        elif char == "`":
            in_template_literal = True
        elif in_template_literal and template_expr_depth > 0:
            if char == "{":
                template_expr_depth += 1
            elif char == "}":
                template_expr_depth -= 1

        index += 1

    return in_template_literal, template_expr_depth


def static_executable_lines(source: str) -> set[int]:
    """Infer executable line numbers from JS/TS source text.

    This is intentionally heuristic rather than a full parser. Its purpose is to
    ensure uncovered files still report a non-zero statement count, while keeping
    line numbers close to what the V8 runtime coverage data reports for loaded
    files.
    """
    uncommented_source = strip_js_comment_text(source)
    executable_lines: set[int] = set()
    in_ts_interface = False
    ts_interface_balance = 0
    in_ts_type_alias = False
    ts_type_alias_balance = 0
    in_ts_as_cast_object = False
    ts_as_cast_object_balance = 0
    in_template_literal = False
    template_expr_depth = 0
    in_directive_prologue = True

    for line_number, line in enumerate(uncommented_source.splitlines(), start=1):
        stripped = line.strip()
        starts_in_template_literal = in_template_literal and template_expr_depth == 0

        in_template_literal, template_expr_depth = _template_state_after_line(
            line, in_template_literal, template_expr_depth
        )

        if starts_in_template_literal:
            if stripped:
                in_directive_prologue = False
            continue

        if not stripped:
            continue

        if in_ts_interface:
            ts_interface_balance += _delimiter_balance(stripped)
            if ts_interface_balance <= 0:
                in_ts_interface = False
                ts_interface_balance = 0
            continue

        if in_ts_type_alias:
            ts_type_alias_balance += _delimiter_balance(stripped)
            if not _type_alias_continues(stripped, ts_type_alias_balance):
                in_ts_type_alias = False
                ts_type_alias_balance = 0
            continue

        if in_ts_as_cast_object:
            ts_as_cast_object_balance += _delimiter_balance(stripped)
            if ts_as_cast_object_balance <= 0:
                in_ts_as_cast_object = False
                ts_as_cast_object_balance = 0
            continue

        if in_directive_prologue and _is_directive_prologue_line(stripped):
            continue

        in_directive_prologue = False

        if _is_ts_declare_statement(stripped):
            continue

        if _is_ts_as_cast_continuation(stripped):
            continue

        if _starts_ts_as_cast_object_literal(stripped):
            in_ts_as_cast_object = True
            ts_as_cast_object_balance = _delimiter_balance(stripped)

        if _starts_ts_interface(stripped):
            in_ts_interface = True
            ts_interface_balance = _delimiter_balance(stripped)
            if ts_interface_balance <= 0:
                in_ts_interface = False
                ts_interface_balance = 0
            continue

        if _starts_ts_type_alias(stripped):
            in_ts_type_alias = True
            ts_type_alias_balance = _delimiter_balance(stripped)
            if not _type_alias_continues(stripped, ts_type_alias_balance):
                in_ts_type_alias = False
                ts_type_alias_balance = 0
            continue

        if is_executable_line(stripped):
            executable_lines.add(line_number)

    return executable_lines


def executable_lines_for_file(filename: str) -> set[int]:
    """Return cached executable lines for *filename* based on source text."""
    cached = _source_lines_cache.get(filename)
    if cached is not None:
        return cached

    lines = static_executable_lines(Path(filename).read_text(encoding="utf-8"))
    _source_lines_cache[filename] = lines
    return lines
