"""Pytest plugin for JavaScript coverage via Playwright CDP.

Collects V8 coverage from Playwright browser tests and injects it into
pytest-cov's combined report. Only active when ``--cov`` is passed to pytest.

See README for usage.
"""

import warnings
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from coverage.exceptions import CoverageWarning

from pytest_jscov import covplugin
from pytest_jscov.playwright_patch import patch_playwright_browser
from pytest_jscov.source_filtering import filter_line_hits, source_executable_lines
from pytest_jscov.sourcemap import (
    gen_to_orig_line_map,
    normalise_source_key,
    parse_inline_sourcemap,
)
from pytest_jscov.utils import (
    entry_to_line_hits,
    is_js_cov_source,
    matches_cov_source,
    merge_hits,
    url_key_to_path,
)

# ---------------------------------------------------------------------------
# Process a batch of V8 entries into the accumulated store
# ---------------------------------------------------------------------------


def process_entries(
    entries: list[dict],
    accumulated: dict[str, dict[int, int]],
    sources: dict[str, str],
) -> None:
    """Fold V8 coverage *entries* into *accumulated* and *sources*.

    Parameters
    ----------
    entries:
        Raw V8 coverage entries, each augmented with a ``"source"`` key holding
        the script text (fetch via ``Debugger.getScriptSource`` before calling).
    accumulated:
        Mutable dict of ``{script_key: {line: hits}}`` updated in-place.
    sources:
        Mutable dict of ``{script_key: source_text}`` updated in-place.
    """
    for entry in entries:
        url: str = entry.get("url", "")
        path = urlsplit(url).path
        if not path.startswith("/static/"):
            continue

        source: str = entry.get("source", "")
        line_hits = filter_line_hits(source, entry_to_line_hits(entry))

        sourcemap = parse_inline_sourcemap(source)
        if sourcemap:
            gen_to_orig = gen_to_orig_line_map(sourcemap)
            src_contents: list[str] = sourcemap.get("sourcesContent") or []
            src_names: list[str] = sourcemap.get("sources") or []

            orig_hits: dict[int, dict[int, int]] = {}
            for gen_line, count in line_hits.items():
                for src_idx, orig_line in gen_to_orig.get(gen_line, []):
                    orig_hits.setdefault(src_idx, {})
                    orig_hits[src_idx][orig_line] = (
                        orig_hits[src_idx].get(orig_line, 0) + count
                    )

            for src_idx, hits in orig_hits.items():
                key = src_names[src_idx] if src_idx < len(src_names) else url
                key = normalise_source_key(url, key)
                executable_lines = source_executable_lines(
                    key,
                    src_contents[src_idx] if src_idx < len(src_contents) else None,
                )
                if executable_lines is not None:
                    hits = {
                        line: count
                        for line, count in hits.items()
                        if line in executable_lines
                    }
                accumulated[key] = merge_hits(accumulated.get(key, {}), hits)
                if key not in sources and src_idx < len(src_contents):
                    sources[key] = src_contents[src_idx]
        else:
            accumulated[path] = merge_hits(accumulated.get(path, {}), line_hits)
            if path not in sources:
                sources[path] = source


# ---------------------------------------------------------------------------
# Pytest plugin
# ---------------------------------------------------------------------------


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
        patch_playwright_browser(config, self, process_entries, is_pytest_cov_active)


def resolve_static_root(session: pytest.Session) -> str:
    """Return the static root path from the active coverage.py config."""
    ctrl = getattr(
        session.config.pluginmanager.get_plugin("_cov"), "cov_controller", None
    )
    cov = getattr(ctrl, "cov", None)
    if cov is None:
        return ""
    try:
        return cov.config.get_option("pytest_jscov.covplugin:static_root") or ""
    except Exception:
        return ""


def path_based_cov_sources(session: pytest.Session) -> list[Path] | None:
    """Return existing path-based --cov targets, or None when unfiltered."""
    ctrl = getattr(
        session.config.pluginmanager.get_plugin("_cov"), "cov_controller", None
    )
    cov_source = getattr(ctrl, "cov_source", None)
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
    ctrl = getattr(
        session.config.pluginmanager.get_plugin("_cov"), "cov_controller", None
    )
    cov_source = getattr(ctrl, "cov_source", None)
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

    cov_plugin = session.config.pluginmanager.get_plugin("_cov")
    ctrl = getattr(cov_plugin, "cov_controller", None)
    cov = getattr(ctrl, "cov", None)
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


def is_pytest_cov_active(config: pytest.Config) -> bool:
    """Return True if pytest-cov is installed, --cov was passed, and is not disabled."""
    cov_plugin = config.pluginmanager.get_plugin("_cov")
    return (
        cov_plugin is not None
        and getattr(cov_plugin, "cov_controller", None) is not None
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the JsCovPlugin and patch Playwright."""
    plugin = JsCovPlugin()
    config.pluginmanager.register(plugin, JsCovPlugin.name)
    plugin.patch_playwright(config)
