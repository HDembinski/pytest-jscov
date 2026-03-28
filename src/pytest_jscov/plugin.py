"""Pytest plugin for JavaScript coverage via Playwright CDP.

Collects V8 coverage from Playwright browser tests and injects it into
pytest-cov's combined report. Only active when ``--cov`` is passed to pytest.

Usage in a project conftest.py
-------------------------------
Use the ``jscov`` fixture as an async context manager around page usage::

    @pytest.fixture
    async def page(browser, jscov):
        context = await browser.new_context()
        page = await context.new_page()
        async with jscov(context, page, base_url):
            await page.goto(base_url)
            yield page
        await page.close()
        await context.close()

The ``jscov`` fixture is a no-op when ``--cov`` is not active, so no
``if`` guard is needed.
"""

import base64
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from pytest_jscov import covplugin

# ---------------------------------------------------------------------------
# VLQ decoder (for sourcemap `mappings` field)
# ---------------------------------------------------------------------------

_B64 = {
    c: i
    for i, c in enumerate(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    )
}


def _vlq_decode_one(s: str, pos: int) -> tuple[int, int]:
    """Decode one VLQ integer starting at *pos* in *s*. Return (value, next_pos)."""
    value = shift = 0
    while True:
        digit = _B64[s[pos]]
        pos += 1
        value |= (digit & 0x1F) << shift
        shift += 5
        if not (digit & 0x20):
            break
    return (-(value >> 1) if value & 1 else value >> 1), pos


def _vlq_decode_segment(s: str) -> list[int]:
    """Decode all VLQ integers in one mapping segment (no commas)."""
    values, pos = [], 0
    while pos < len(s):
        v, pos = _vlq_decode_one(s, pos)
        values.append(v)
    return values


# ---------------------------------------------------------------------------
# Sourcemap parsing
# ---------------------------------------------------------------------------

_SOURCEMAP_RE = re.compile(
    r"//# sourceMappingURL=data:application/json;base64,([A-Za-z0-9+/=]+)"
)


def _parse_inline_sourcemap(source: str) -> dict | None:
    """Extract and decode an inline sourcemap comment from JS source."""
    m = _SOURCEMAP_RE.search(source)
    if not m:
        return None
    return json.loads(base64.b64decode(m.group(1)))


def _gen_to_orig_line_map(sourcemap: dict) -> dict[int, list[tuple[int, int]]]:
    """
    Build generated_line (1-based) → [(source_idx, orig_line_1based)] from sourcemap.

    Only the first source file is normally present for single-file esbuild output.
    """
    mappings = sourcemap.get("mappings", "")
    gen_to_orig: dict[int, list[tuple[int, int]]] = {}

    src_idx = orig_line = orig_col = 0
    for gen_line_idx, line_str in enumerate(mappings.split(";")):
        gen_line = gen_line_idx + 1
        gen_col = 0
        for seg_str in line_str.split(","):
            if not seg_str:
                continue
            fields = _vlq_decode_segment(seg_str)
            gen_col += fields[0]
            if len(fields) >= 4:
                src_idx += fields[1]
                orig_line += fields[2]
                orig_col += fields[3]
                gen_to_orig.setdefault(gen_line, []).append((src_idx, orig_line + 1))

    return gen_to_orig


# ---------------------------------------------------------------------------
# Byte offset → line number
# ---------------------------------------------------------------------------


def _line_offsets(source: str) -> list[int]:
    """Return a list where index i holds the byte offset of the start of line i+1."""
    offsets = [0]
    for i, c in enumerate(source):
        if c == "\n":
            offsets.append(i + 1)
    return offsets


# ---------------------------------------------------------------------------
# V8 coverage entry → per-line hit counts
# ---------------------------------------------------------------------------


def entry_to_line_hits(entry: dict) -> dict[int, int]:
    """Convert one V8 coverage entry to {1-based line: hit_count}.

    Only executable lines (those inside at least one range) are included.
    For each line, the *innermost* (smallest) containing range's count is used.
    """
    source: str = entry.get("source", "")
    if not source:
        return {}

    offsets = _line_offsets(source)

    all_ranges: list[tuple[int, int, int]] = []
    for func in entry.get("functions", []):
        for rng in func["ranges"]:
            all_ranges.append((rng["startOffset"], rng["endOffset"], rng["count"]))

    if not all_ranges:
        return {}

    result: dict[int, int] = {}
    for line_idx, line_start in enumerate(offsets):
        line_num = line_idx + 1
        best_count: int | None = None
        best_size = float("inf")
        for start, end, count in all_ranges:
            if start <= line_start < end:
                size = end - start
                if size < best_size:
                    best_size = size
                    best_count = count
        if best_count is not None:
            result[line_num] = best_count

    return result


# ---------------------------------------------------------------------------
# Aggregate coverage across multiple test runs
# ---------------------------------------------------------------------------


def _merge_hits(
    accumulated: dict[int, int], new_hits: dict[int, int]
) -> dict[int, int]:
    merged = dict(accumulated)
    for line, count in new_hits.items():
        merged[line] = merged.get(line, 0) + count
    return merged


# ---------------------------------------------------------------------------
# Process a batch of V8 entries into the accumulated store
# ---------------------------------------------------------------------------


def process_entries(
    entries: list[dict],
    base_url: str,
    accumulated: dict[str, dict[int, int]],
    sources: dict[str, str],
) -> None:
    """Fold V8 coverage *entries* into *accumulated* and *sources*.

    Parameters
    ----------
    entries:
        Raw V8 coverage entries, each augmented with a ``"source"`` key holding
        the script text (fetch via ``Debugger.getScriptSource`` before calling).
    base_url:
        Server base URL (e.g. ``"http://127.0.0.1:8765"``).  Only scripts
        whose URL starts with ``base_url + "/static/"`` are recorded.
    accumulated:
        Mutable dict of ``{script_key: {line: hits}}`` updated in-place.
    sources:
        Mutable dict of ``{script_key: source_text}`` updated in-place.
    """
    prefix = base_url.rstrip("/") + "/static/"

    for entry in entries:
        url: str = entry.get("url", "")
        if not url.startswith(prefix):
            continue

        source: str = entry.get("source", "")
        line_hits = entry_to_line_hits(entry)

        sourcemap = _parse_inline_sourcemap(source)
        if sourcemap:
            gen_to_orig = _gen_to_orig_line_map(sourcemap)
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
                key = _normalise_source_key(url, key)
                accumulated[key] = _merge_hits(accumulated.get(key, {}), hits)
                if key not in sources and src_idx < len(src_contents):
                    sources[key] = src_contents[src_idx]
        else:
            key = url[len(base_url.rstrip("/")) :]  # strip host, keep /static/…
            accumulated[key] = _merge_hits(accumulated.get(key, {}), line_hits)
            if key not in sources:
                sources[key] = source


def _normalise_source_key(script_url: str, source_path: str) -> str:
    """Resolve a sourcemap source path to a canonical key.

    Returns an absolute filesystem path for filesystem sources (esbuild emits
    cwd-relative paths like ``src/myapp/static/foo.ts``), or a full URL for
    URL-space sources.
    """
    if source_path.startswith(("http://", "https://")):
        return source_path
    # Windows absolute path ("C:/...") or Unix absolute path ("/...")
    if source_path.startswith("/") or (len(source_path) >= 2 and source_path[1] == ":"):
        return str(Path(source_path).resolve())
    # Relative path starting with "./" or "../": resolve against script URL.
    if source_path.startswith(("./", "../")):
        base = script_url.rsplit("/", 1)[0] + "/"
        parts = (base + source_path).split("/")
        resolved: list[str] = []
        for part in parts:
            if part == "..":
                if resolved:
                    resolved.pop()
            elif part != ".":
                resolved.append(part)
        return "/".join(resolved)
    # Bare relative path (no leading ./ or ../) — esbuild uses cwd-relative
    # paths when outputting to stdout regardless of the input path.
    return str(Path(source_path).resolve())


# ---------------------------------------------------------------------------
# Pytest plugin
# ---------------------------------------------------------------------------


class JsCovPlugin:
    """Holds accumulated coverage state and injects it into pytest-cov."""

    # Distinct from the entry-point name ("jscov") used for the module itself.
    name = "_jscov_collector"

    def __init__(self) -> None:
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
        static_root = _resolve_static_root(session)
        if static_root:
            _inject_into_pytest_cov(session, self.accumulated, static_root)


def _resolve_static_root(session: pytest.Session) -> str:
    """Return the static root path, from CLI option or coverage.py config.

    Priority:
    1. ``--jscov-static-root`` CLI option (explicit override)
    2. ``static_root`` from ``[tool.coverage.pytest_jscov.covplugin]`` in
       pyproject.toml / .coveragerc (read via the active Coverage object)
    """
    cli = session.config.getoption("--jscov-static-root", default="") or ""
    if cli:
        return cli
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


def _url_key_to_path(key: str, static_root: str) -> Path | None:
    """Map a coverage key to an absolute filesystem path.

    Keys are either absolute filesystem paths (produced by sourcemap resolution
    for esbuild-compiled TypeScript) or URL-based keys for plain JS files.
    """
    p = Path(key)
    if p.is_absolute():
        return p
    # URL key: strip scheme+host, then the leading "/static/" segment.
    if key.startswith(("http://", "https://")):
        key = key[key.index("/", 8) :]
    static_prefix = "/static/"
    if not key.startswith(static_prefix):
        return None
    rel = key[len(static_prefix) :]
    return (Path(static_root) / rel).resolve()


def _inject_into_pytest_cov(
    session: pytest.Session,
    accumulated: dict[str, dict[int, int]],
    static_root: str,
) -> None:
    """Merge JS line hits into the active pytest-cov Coverage object."""
    lines_cache: dict[str, list[int]] = {}
    executed: dict[str, dict[int, None]] = {}

    for key, hits in accumulated.items():
        path = _url_key_to_path(key, static_root)
        if path is None or not path.exists():
            continue
        path_str = str(path)
        lines_cache[path_str] = sorted(hits.keys())
        executed[path_str] = {line: None for line, count in hits.items() if count > 0}

    covplugin._lines_data.update(lines_cache)

    try:
        import coverage as coverage_module
    except ImportError:
        return

    cov_plugin = session.config.pluginmanager.get_plugin("_cov")
    ctrl = getattr(cov_plugin, "cov_controller", None)
    cov = getattr(ctrl, "cov", None)
    if cov is None:
        return

    # Write JS data as .coverage.jscov so it is automatically included in
    # pytest-cov's combine step.  The file tracer name must match what
    # covplugin.JsFilePlugin registers to avoid "Conflicting file tracer".
    tracer_name = "pytest_jscov.covplugin.JsFilePlugin"
    data_file = cov.config.data_file  # typically ".coverage"
    js_file = f"{data_file}.jscov"

    # When --cov-branch is active, coverage.py refuses to combine line data
    # with arc data.  Synthesise arcs from our line hits so the formats match.
    branch = getattr(cov.config, "branch", False)
    js_data = coverage_module.CoverageData(basename=js_file)
    if branch:
        arcs = {
            path: {(-1, line): None for line in lines}
            for path, lines in executed.items()
        }
        js_data.add_arcs(arcs)
    else:
        js_data.add_lines(executed)
    js_data.add_file_tracers({path: tracer_name for path in executed})
    js_data.write()


def _pytest_cov_active(config: pytest.Config) -> bool:
    """Return True if pytest-cov is installed, --cov was passed, and is not disabled."""
    cov_plugin = config.pluginmanager.get_plugin("_cov")
    return (
        cov_plugin is not None
        and getattr(cov_plugin, "cov_controller", None) is not None
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--jscov-static-root",
        default="",
        metavar="PATH",
        help=(
            "Filesystem path to the static files root (e.g. src/myapp/static). "
            "Overrides static_root from [tool.coverage.pytest_jscov.covplugin]. "
            "When available (via CLI or coverage config), JS coverage is merged "
            "into pytest-cov's combined report."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(JsCovPlugin(), JsCovPlugin.name)


@asynccontextmanager
async def _noop_context(context, page, base_url) -> AsyncIterator[None]:
    yield


@asynccontextmanager
async def _cdp_coverage(
    context, page, base_url: str, plugin: JsCovPlugin
) -> AsyncIterator[None]:
    """Start V8 coverage via CDP, collect on exit, and fold into *plugin*."""
    cdp = await context.new_cdp_session(page)
    await cdp.send("Profiler.enable")
    await cdp.send("Debugger.enable")
    await cdp.send(
        "Profiler.startPreciseCoverage", {"callCount": True, "detailed": True}
    )
    yield
    result = await cdp.send("Profiler.takePreciseCoverage")
    entries = result.get("result", [])
    for entry in entries:
        try:
            src = await cdp.send(
                "Debugger.getScriptSource", {"scriptId": entry["scriptId"]}
            )
            entry["source"] = src.get("scriptSource", "")
        except Exception:
            entry["source"] = ""
    await cdp.detach()
    process_entries(entries, base_url, plugin.accumulated, plugin.sources)


@pytest.fixture
def jscov(request: pytest.FixtureRequest):
    """Async context manager that collects V8 JS coverage via Playwright CDP.

    Returns a no-op context manager when pytest-cov is not active, so callers
    don't need an ``if`` guard.  Usage::

        @pytest.fixture
        async def page(browser, jscov):
            context = await browser.new_context()
            page = await context.new_page()
            async with jscov(context, page, base_url):
                await page.goto(base_url)
                yield page
            await page.close()
            await context.close()
    """
    if not _pytest_cov_active(request.config):
        return _noop_context
    plugin: JsCovPlugin | None = request.config.pluginmanager.get_plugin(
        JsCovPlugin.name
    )
    assert plugin is not None
    return lambda context, page, base_url: _cdp_coverage(
        context, page, base_url, plugin
    )
