"""coverage.py plugin for JavaScript/TypeScript files.

Register this in your .coveragerc (or pyproject.toml [tool.coverage.run]) to
include JS/TS files in the combined Python + JS coverage report::

    [run]
    plugins = pytest_jscov.covplugin

    [pytest_jscov.covplugin]
    static_root = src/myapp/static

Then run::

    pytest --cov=src --jscov --jscov-static-root=src/myapp/static

The plugin reads executable-line data from .jscov_lines.json written by the
pytest plugin, so precise V8 executable lines are used rather than a heuristic.
"""

from __future__ import annotations

from pathlib import Path

import coverage
from coverage.plugin_support import Plugins

# Populated by pytest_jscov.plugin._inject_into_pytest_cov before the report
# is generated.  Maps absolute path → sorted list of executable line numbers.
_lines_data: dict[str, list[int]] = {}


class JsFilePlugin(coverage.CoveragePlugin):
    def __init__(self, options: dict) -> None:
        self._static_root = options.get("static_root", "")

    def file_reporter(self, filename: str) -> "coverage.FileReporter":
        return JsFileReporter(filename)

    def file_tracer(self, filename: str) -> None:
        # We inject coverage data directly; no runtime tracing needed.
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
    def source(self) -> str:
        return Path(self.filename).read_text(encoding="utf-8")

    def lines(self) -> set[int]:
        """Return executable lines from V8 coverage data."""
        return set(_lines_data.get(self.filename, []))


def coverage_init(reg: Plugins, options: dict) -> None:
    reg.add_file_tracer(JsFilePlugin(options))
