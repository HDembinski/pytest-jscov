"""Tests for the static executable-line detector."""

from pathlib import Path

import pytest

from pytest_jscov.executable_lines import static_executable_lines
from pytest_jscov.plugin import _filter_line_hits, entry_to_line_hits

DATA_DIR = Path(__file__).parent / "data"


def _fixture_source(name: str) -> str:
    return (DATA_DIR / name).read_text(encoding="utf-8")


EXPECTED_LINES = [
    ("static/detector_classic.js", {2, 7, 8, 9, 12}),
    ("static/detector_module.js", {2, 7, 8, 9, 11}),
]


@pytest.mark.parametrize(("filename", "expected_lines"), EXPECTED_LINES)
def test_static_executable_lines_for_detector_fixtures(filename, expected_lines):
    """The line detector should classify the fixture files predictably."""
    assert static_executable_lines(_fixture_source(filename)) == expected_lines


def test_static_executable_lines_ignore_typescript_only_constructs():
    """Directive prologues and TS-only declarations should not count as executable."""
    source = _fixture_source("typescript_only.ts")

    assert static_executable_lines(source) == {12, 13}


def test_static_executable_lines_ignore_template_continuations_and_as_casts():
    """Template continuation lines and TS `as`-cast continuations are ignored."""
    source = _fixture_source("template_continuations_and_as_casts.ts")

    assert static_executable_lines(source) == {3, 6, 7}


def test_static_executable_lines_ignore_as_cast_object_literal_members():
    """Type members inside multiline `as Foo & { ... }` casts are ignored."""
    source = _fixture_source("as_cast_object_literal_members.ts")

    assert static_executable_lines(source) == {3}


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
    assert filtered_cdp_lines == static_executable_lines(entry["source"])
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
