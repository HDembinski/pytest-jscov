"""Helpers for filtering coverage data down to reportable source lines."""

from pathlib import Path

from pytest_jscov.executable_lines import (
    executable_lines_for_file,
    static_executable_lines,
)


def filter_line_hits(source: str, line_hits: dict[int, int]) -> dict[int, int]:
    """Keep only line hits that the static detector considers executable."""
    executable_lines = static_executable_lines(source)
    return {
        line: count for line, count in line_hits.items() if line in executable_lines
    }


def source_executable_lines(key: str, source_text: str | None) -> set[int] | None:
    """Return executable lines for a source-mapped file when available."""
    if source_text:
        return static_executable_lines(source_text)

    path = Path(key)
    if path.is_absolute() and path.exists():
        return executable_lines_for_file(str(path))

    return None
