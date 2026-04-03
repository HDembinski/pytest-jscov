"""Tests for the static executable-line detector."""

import functools
import http.server
import threading
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from pytest_jscov.covplugin import _static_executable_lines
from pytest_jscov.plugin import _filter_line_hits, entry_to_line_hits

DATA_DIR = Path(__file__).parent / "data"
STATIC_DIR = DATA_DIR / "static"


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(DATA_DIR)
    )
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture(scope="module")
async def browser():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        yield browser
        await browser.close()


def _fixture_source(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


EXPECTED_LINES = [
    ("detector_classic.js", {2, 7, 8, 9, 12}),
    ("detector_module.js", {2, 7, 8, 9, 11}),
]


@pytest.mark.parametrize(("filename", "expected_lines"), EXPECTED_LINES)
def test_static_executable_lines_for_detector_fixtures(filename, expected_lines):
    """The line detector should classify the fixture files predictably."""
    assert _static_executable_lines(_fixture_source(filename)) == expected_lines


async def _coverage_entry_for(page, script_name: str) -> dict:
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("Profiler.enable")
    await cdp.send("Debugger.enable")
    await cdp.send(
        "Profiler.startPreciseCoverage", {"callCount": True, "detailed": True}
    )

    try:
        await page.goto(f"{page._base_url}/detector.html")
        payload = await cdp.send("Profiler.takePreciseCoverage")
    finally:
        await cdp.send("Profiler.stopPreciseCoverage")

    for entry in payload.get("result", []):
        if entry.get("url", "").endswith(script_name):
            source = await cdp.send(
                "Debugger.getScriptSource", {"scriptId": entry["scriptId"]}
            )
            entry["source"] = source.get("scriptSource", "")
            return entry

    raise AssertionError(f"coverage entry for {script_name} not found")


@pytest.mark.parametrize(("script_name", "expected_lines"), EXPECTED_LINES)
async def test_static_detector_filters_cdp_line_hits(
    browser, base_url, script_name, expected_lines
):
    """Filtered CDP line hits should use the detector's executable-line model."""
    page = await browser.new_page()
    page._base_url = base_url
    try:
        entry = await _coverage_entry_for(page, script_name)
    finally:
        await page.close()

    raw_cdp_lines = set(entry_to_line_hits(entry))
    filtered_cdp_lines = set(
        _filter_line_hits(entry["source"], entry_to_line_hits(entry))
    )

    assert filtered_cdp_lines == expected_lines
    assert filtered_cdp_lines == _static_executable_lines(entry["source"])
    assert raw_cdp_lines >= filtered_cdp_lines


@pytest.mark.parametrize(("script_name", "expected_lines"), EXPECTED_LINES)
async def test_raw_cdp_line_projection_is_broader_than_detector_for_complex_cases(
    browser, base_url, script_name, expected_lines
):
    """The raw V8 range-to-line projection can include non-executable lines."""
    page = await browser.new_page()
    page._base_url = base_url
    try:
        entry = await _coverage_entry_for(page, script_name)
    finally:
        await page.close()

    raw_cdp_lines = set(entry_to_line_hits(entry))

    assert raw_cdp_lines != expected_lines
    assert raw_cdp_lines > expected_lines
