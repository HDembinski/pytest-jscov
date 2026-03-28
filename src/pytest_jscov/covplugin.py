"""coverage.py plugin for JavaScript/TypeScript files.

Register this in your .coveragerc (or pyproject.toml [tool.coverage.run]) to
include JS/TS files in the combined Python + JS coverage report::

See README for usage.
"""

from __future__ import annotations

from pathlib import Path

import coverage
from coverage.plugin_support import Plugins

# Populated by pytest_jscov.plugin._inject_into_pytest_cov before the report
# is generated.  Maps absolute path → sorted list of executable line numbers.
_lines_data: dict[str, list[int]] = {}


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
        """Yield JS/TS files under static_root (or src_dir as fallback)."""
        root = Path(self._static_root) if self._static_root else Path(src_dir)
        if not root.is_dir():
            return
        skip = {"node_modules", "vendor", ".venv"}
        for pattern in ("*.js", "*.ts"):
            for p in root.rglob(pattern):
                if not any(part in skip for part in p.parts):
                    # Exclude .d.ts declaration files — no executable code.
                    if not p.name.endswith(".d.ts"):
                        yield str(p.resolve())


class JsFileReporter(coverage.FileReporter):
    """File reporter that reads JS/TS source and provides executable lines."""

    def source(self) -> str:
        """Return the source text of the file."""
        return Path(self.filename).read_text(encoding="utf-8")

    def lines(self) -> set[int]:
        """Return executable lines from V8 coverage data."""
        return set(_lines_data.get(self.filename, []))


def coverage_init(reg: Plugins, options: dict) -> None:
    """Entry point called by coverage.py to register the plugin."""
    reg.add_file_tracer(JsFilePlugin(options))
