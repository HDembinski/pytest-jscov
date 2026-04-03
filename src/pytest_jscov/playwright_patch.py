"""Playwright monkeypatching for automatic JS coverage collection."""

from collections.abc import Callable
from typing import Protocol

import pytest
from playwright.async_api import Browser


class CoverageStore(Protocol):
    """Protocol for the coverage state used by Playwright instrumentation."""

    accumulated: dict[str, dict[int, int]]
    sources: dict[str, str]


ProcessEntries = Callable[[list[dict], dict[str, dict[int, int]], dict[str, str]], None]
PytestCovActive = Callable[[pytest.Config], bool]


def patch_playwright_browser(
    config: pytest.Config,
    plugin: CoverageStore,
    process_entries: ProcessEntries,
    pytest_cov_active: PytestCovActive,
) -> None:
    """Patch Playwright browser creation helpers when coverage is active."""
    if not pytest_cov_active(config):
        return

    original_new_context = Browser.new_context
    original_new_page = Browser.new_page

    async def new_context(self, *args, **kwargs):
        context = await original_new_context(self, *args, **kwargs)
        await _instrument_context(context, plugin, process_entries)
        return context

    async def new_page(self, *args, **kwargs):
        page = await original_new_page(self, *args, **kwargs)
        await _instrument_context(page.context, plugin, process_entries)
        await _instrument_page(page.context, page, plugin, process_entries)
        return page

    setattr(Browser, "new_context", new_context)
    setattr(Browser, "new_page", new_page)


async def _instrument_page(
    context,
    page,
    plugin: CoverageStore,
    process_entries: ProcessEntries,
) -> None:
    """Attach CDP coverage tracking and helper methods to one page."""
    cdp = await context.new_cdp_session(page)

    async def save_coverage() -> None:
        """Read one batch of V8 coverage data and fold it into *plugin*."""
        try:
            result = await cdp.send("Profiler.takePreciseCoverage")
        except Exception:
            return
        entries = result.get("result", [])
        for entry in entries:
            try:
                src = await cdp.send(
                    "Debugger.getScriptSource", {"scriptId": entry["scriptId"]}
                )
                entry["source"] = src.get("scriptSource", "")
            except Exception:
                entry["source"] = ""
        process_entries(entries, plugin.accumulated, plugin.sources)

    setattr(page, "save_coverage", save_coverage)

    for method_name in ("reload", "goto", "go_back", "go_forward", "close"):
        original = getattr(page, method_name)
        assert original is not None, f"expected page to have method {method_name}"

        async def wrapped(*args, _original=original, **kwargs):
            await save_coverage()
            return await _original(*args, **kwargs)

        setattr(page, method_name, wrapped)

    await cdp.send("Profiler.enable")
    await cdp.send("Debugger.enable")
    await cdp.send(
        "Profiler.startPreciseCoverage", {"callCount": True, "detailed": True}
    )


async def _instrument_context(
    context,
    plugin: CoverageStore,
    process_entries: ProcessEntries,
):
    """Patch a BrowserContext to auto-instrument pages for coverage."""
    instrumented_pages = []
    original_new_page = getattr(context, "new_page")
    original_close = getattr(context, "close")

    async def new_page(*args, **kwargs):
        page = await original_new_page(*args, **kwargs)
        await _instrument_page(context, page, plugin, process_entries)
        instrumented_pages.append(page)
        return page

    async def close(*args, **kwargs):
        for page in list(instrumented_pages):
            await page.save_coverage()
        return await original_close(*args, **kwargs)

    setattr(context, "new_page", new_page)
    setattr(context, "close", close)

    return context
