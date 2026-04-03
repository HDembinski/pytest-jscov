"""coverage.py plugin for JavaScript/TypeScript files.

Register this in your .coveragerc (or pyproject.toml [tool.coverage.run]) to
include JS/TS files in the combined Python + JS coverage report::

See README for usage.
"""

from __future__ import annotations

import re
from pathlib import Path

import coverage
from coverage.plugin_support import Plugins

# Populated by pytest_jscov.plugin._inject_into_pytest_cov before the report
# is generated.  Maps absolute path → sorted list of executable line numbers.
_lines_data: dict[str, list[int]] = {}
_source_lines_cache: dict[str, set[int]] = {}

_STRUCTURAL_LINE_RE = re.compile(r"^[{}()[\],;]+$")
_NON_EXECUTABLE_KEYWORDS = {"do", "else", "finally", "try"}


def _is_relative_to(path: Path, other: Path) -> bool:
    """Return True when *path* is equal to or contained in *other*."""
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def _is_reportable_js(path: Path) -> bool:
    """Return True for reportable JS/TS source files."""
    if path.suffix not in {".js", ".ts"}:
        return False
    if path.name.endswith(".d.ts"):
        return False
    return not any(part in {"node_modules", "vendor", ".venv"} for part in path.parts)


def _iter_reportable_js(target: Path):
    """Yield reportable JS/TS files from *target*."""
    if target.is_file():
        if _is_reportable_js(target):
            yield str(target.resolve())
        return

    for pattern in ("*.js", "*.ts"):
        for path in target.rglob(pattern):
            if _is_reportable_js(path):
                yield str(path.resolve())


def _strip_js_comment_text(source: str) -> str:
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


def _is_executable_line(text: str) -> bool:
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


def _static_executable_lines(source: str) -> set[int]:
    """Infer executable line numbers from JS/TS source text.

    This is intentionally heuristic rather than a full parser. Its purpose is to
    ensure uncovered files still report a non-zero statement count, while keeping
    line numbers close to what the V8 runtime coverage data reports for loaded
    files.
    """
    uncommented_source = _strip_js_comment_text(source)
    executable_lines: set[int] = set()

    for line_number, line in enumerate(uncommented_source.splitlines(), start=1):
        if _is_executable_line(line.strip()):
            executable_lines.add(line_number)

    return executable_lines


def _executable_lines_for_file(filename: str) -> set[int]:
    """Return cached executable lines for *filename* based on source text."""
    cached = _source_lines_cache.get(filename)
    if cached is not None:
        return cached

    lines = _static_executable_lines(Path(filename).read_text(encoding="utf-8"))
    _source_lines_cache[filename] = lines
    return lines


class JsFilePlugin(coverage.CoveragePlugin):
    """Coverage plugin that reports JS/TS files under a static root."""

    def __init__(self, options: dict) -> None:
        """Initialize with options from the coverage config section."""
        self._static_root = options.get("static_root", "")

    def file_reporter(self, filename: str) -> coverage.FileReporter:
        """Return a reporter for the given JS/TS file."""
        return JsFileReporter(filename)

    def file_tracer(self, filename: str) -> None:
        """Return None; coverage data is injected directly, not traced at runtime."""
        return None

    def find_executable_files(self, src_dir: str):
        """Yield JS/TS files that match the active coverage source target."""
        static_root = Path(self._static_root).resolve() if self._static_root else None
        src_path = Path(src_dir)

        if src_path.exists():
            src_path = src_path.resolve()
            if src_path.is_file():
                yield from _iter_reportable_js(src_path)
                return

            if static_root and static_root.is_dir():
                if _is_relative_to(static_root, src_path):
                    yield from _iter_reportable_js(static_root)
                    return
                if _is_relative_to(src_path, static_root):
                    yield from _iter_reportable_js(src_path)
                    return
                return

            yield from _iter_reportable_js(src_path)
            return

        if static_root and static_root.is_dir():
            yield from _iter_reportable_js(static_root)


class JsFileReporter(coverage.FileReporter):
    """File reporter that reads JS/TS source and provides executable lines."""

    def source(self) -> str:
        """Return the source text of the file."""
        return Path(self.filename).read_text(encoding="utf-8")

    def lines(self) -> set[int]:
        """Return executable lines inferred from the source text."""
        return _executable_lines_for_file(self.filename)


def coverage_init(reg: Plugins, options: dict) -> None:
    """Entry point called by coverage.py to register the plugin."""
    reg.add_file_tracer(JsFilePlugin(options))
