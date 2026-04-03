"""coverage.py plugin for JavaScript/TypeScript files.

Register this in your .coveragerc (or pyproject.toml [tool.coverage.run]) to
include JS/TS files in the combined Python + JS coverage report::

See README for usage.
"""

from __future__ import annotations

from pathlib import Path

import coverage
from coverage.plugin_support import Plugins

from pytest_jscov.executable_lines import executable_lines_for_file

# Populated by pytest_jscov.plugin._inject_into_pytest_cov before the report
# is generated.  Maps absolute path → sorted list of executable line numbers.
_lines_data: dict[str, list[int]] = {}


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


class JsCoverageConfigurer(coverage.CoveragePlugin):
    """Force a coverage core that supports file tracer plugins."""

    def configure(self, config) -> None:
        """Select the ctrace core required for coverage plugin reporting."""
        if config.get_option("run:core") != "ctrace":
            config.set_option("run:core", "ctrace")


class JsFileReporter(coverage.FileReporter):
    """File reporter that reads JS/TS source and provides executable lines."""

    def source(self) -> str:
        """Return the source text of the file."""
        return Path(self.filename).read_text(encoding="utf-8")

    def lines(self) -> set[int]:
        """Return executable lines inferred from the source text."""
        return executable_lines_for_file(self.filename)


def coverage_init(reg: Plugins, options: dict) -> None:
    """Entry point called by coverage.py to register the plugin."""
    reg.add_configurer(JsCoverageConfigurer())
    reg.add_file_tracer(JsFilePlugin(options))
