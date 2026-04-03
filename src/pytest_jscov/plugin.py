"""Pytest plugin for JavaScript coverage via Playwright CDP.

Collects V8 coverage from Playwright browser tests and injects it into
pytest-cov's combined report. Only active when ``--cov`` is passed to pytest.

See README for usage.
"""

import warnings
from pathlib import Path

import pytest
from coverage.exceptions import CoverageWarning

from pytest_jscov import covplugin
from pytest_jscov.playwright_patch import patch_playwright_browser
from pytest_jscov.utils import (
    get_pytest_cov_attr,
    is_js_cov_source,
    matches_cov_source,
    url_key_to_path,
)


class JsCovPlugin:
    """Holds accumulated coverage state and injects it into pytest-cov."""

    # Distinct from the entry-point name ("jscov") used for the module itself.
    name = "_jscov_collector"

    def __init__(self) -> None:
        """Initialize empty coverage accumulators."""
        self.accumulated: dict[str, dict[int, int]] = {}
        self.sources: dict[str, str] = {}

    @pytest.hookimpl(wrapper=True, trylast=True)
    def pytest_runtestloop(self, session: pytest.Session):
        """Inject JS coverage into pytest-cov before it finalises its report.

        ``trylast=True`` makes this the innermost wrapper, so our post-yield
        code runs before pytest-cov's (which stops coverage and writes the
        report).
        """
        yield
        if not self.accumulated:
            return
        static_root = resolve_static_root(session)
        if static_root:
            inject_into_pytest_cov(session, self.accumulated, static_root)

    def patch_playwright(self, config: pytest.Config) -> None:
        """Install Playwright coverage patching when coverage is active."""
        patch_playwright_browser(config, self)


def resolve_static_root(session: pytest.Session) -> str:
    """Return the static root path from the active coverage.py config."""
    cov = get_pytest_cov_attr(session.config, "cov")
    if cov is None:
        return ""
    try:
        return cov.config.get_option("pytest_jscov.covplugin:static_root") or ""
    except Exception:
        return ""


def path_based_cov_sources(session: pytest.Session) -> list[Path] | None:
    """Return existing path-based --cov targets, or None when unfiltered."""
    cov_source = get_pytest_cov_attr(session.config, "cov_source")
    if cov_source is None:
        return None

    source_paths: list[Path] = []
    for source in cov_source:
        path = Path(source)
        if path.exists():
            source_paths.append(path.resolve())

    return source_paths or None


def has_only_js_cov_sources(session: pytest.Session) -> bool:
    """Return True when every explicit --cov source targets JS/TS content only."""
    cov_source = get_pytest_cov_attr(session.config, "cov_source")
    if not cov_source:
        return False

    for source in cov_source:
        path = Path(source)
        if not path.exists():
            return False
        path = path.resolve()
        if not is_js_cov_source(path):
            return False

    return True


def filter_false_positive_js_warnings(session: pytest.Session) -> None:
    """Ignore false-positive coverage warnings for explicit JS file targets.

    coverage.py treats ``--cov=path/to/file.js`` as a Python source target and
    emits ``module-not-imported`` and ``no-data-collected`` warnings before the
    injected JS data is reported. Those warnings are false positives for this
    plugin's file-based JS coverage mode.
    """
    if not has_only_js_cov_sources(session):
        return

    warnings.filterwarnings(
        "ignore",
        message=".+module-not-imported",
        category=CoverageWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=".+no-data-collected",
        category=CoverageWarning,
    )


def inject_into_pytest_cov(
    session: pytest.Session,
    accumulated: dict[str, dict[int, int]],
    static_root: str,
) -> None:
    """Merge JS line hits into the active pytest-cov Coverage object."""
    lines_cache: dict[str, list[int]] = {}
    executed: dict[str, dict[int, None]] = {}
    filter_false_positive_js_warnings(session)
    source_paths = path_based_cov_sources(session)

    for key, hits in accumulated.items():
        path = url_key_to_path(key, static_root)
        if path is None or not path.exists():
            continue
        path = path.resolve()
        if not matches_cov_source(path, source_paths):
            continue
        path_str = str(path)
        lines_cache[path_str] = sorted(hits.keys())
        executed[path_str] = {line: None for line, count in hits.items() if count > 0}

    covplugin._lines_data.update(lines_cache)

    cov = get_pytest_cov_attr(session.config, "cov")
    if cov is None:
        return

    # Inject directly into the active Coverage object's data store.
    # This runs before pytest-cov's post-yield (which stops, saves, and
    # reports), so the JS data will be included in the final report.
    tracer_name = "pytest_jscov.covplugin.JsFilePlugin"
    branch = getattr(cov.config, "branch", False)
    cov_data = cov.get_data()
    if branch:
        arcs = {
            path: {(-1, line): None for line in lines}
            for path, lines in executed.items()
        }
        cov_data.add_arcs(arcs)
    else:
        cov_data.add_lines(executed)
    cov_data.add_file_tracers({path: tracer_name for path in executed})


def pytest_configure(config: pytest.Config) -> None:
    """Register the JsCovPlugin and patch Playwright."""
    plugin = JsCovPlugin()
    config.pluginmanager.register(plugin, JsCovPlugin.name)
    plugin.patch_playwright(config)
