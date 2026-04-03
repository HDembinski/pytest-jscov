"""Playwright monkeypatching for automatic JS coverage collection."""

from typing import Protocol

import pytest
from playwright.async_api import Browser, Page

from pytest_jscov.entry_processing import process_entries
from pytest_jscov.utils import is_pytest_cov_active


class CoverageStore(Protocol):
    """Protocol for the coverage state used by Playwright instrumentation."""

    accumulated: dict[str, dict[int, int]]
    sources: dict[str, str]


class SaveCoverage:
    """Callable coverage saver bound to one instrumented page."""

    def __init__(
        self,
        cdp,
        plugin: CoverageStore,
    ) -> None:
        self._cdp = cdp
        self._plugin = plugin

    async def __call__(self) -> None:
        """Read one batch of V8 coverage data and fold it into the plugin."""
        result = await self._cdp.send("Profiler.takePreciseCoverage")

        entries = result.get("result", [])
        for entry in entries:
            try:
                src = await self._cdp.send(
                    "Debugger.getScriptSource", {"scriptId": entry["scriptId"]}
                )
                entry["source"] = src.get("scriptSource", "")
            except Exception:
                entry["source"] = ""

        process_entries(entries, self._plugin.accumulated, self._plugin.sources)


_PAGE_COVERAGE_SAVERS: dict[int, SaveCoverage] = {}


def _clear_page_coverage_saver(page: Page) -> None:
    """Remove any registered coverage saver for *page*."""
    _PAGE_COVERAGE_SAVERS.pop(id(page), None)


async def save_coverage(page: Page) -> None:
    """Persist one batch of V8 coverage for an instrumented Playwright page."""
    saver = _PAGE_COVERAGE_SAVERS.get(id(page))
    if saver is None:
        return
    await saver()


def _wrap_page_method(page: Page, method_name: str, saver: SaveCoverage) -> None:
    """Wrap one Playwright page method to flush coverage before it runs."""
    original = getattr(page, method_name)
    assert original is not None, f"expected page to have method {method_name}"

    async def wrapped(*args, **kwargs):
        try:
            await saver()
            return await original(*args, **kwargs)
        finally:
            if method_name == "close":
                _clear_page_coverage_saver(page)

    setattr(page, method_name, wrapped)


def patch_playwright_browser(
    config: pytest.Config,
    plugin: CoverageStore,
) -> None:
    """Patch Playwright browser creation helpers when coverage is active."""
    if not is_pytest_cov_active(config):
        return

    original_new_context = Browser.new_context
    original_new_page = Browser.new_page

    async def new_context(self, *args, **kwargs):
        context = await original_new_context(self, *args, **kwargs)
        await _instrument_context(context, plugin)
        return context

    async def new_page(self, *args, **kwargs):
        page = await original_new_page(self, *args, **kwargs)
        await _instrument_context(page.context, plugin)
        await _instrument_page(page.context, page, plugin)
        return page

    setattr(Browser, "new_context", new_context)
    setattr(Browser, "new_page", new_page)


async def _instrument_page(
    context,
    page,
    plugin: CoverageStore,
) -> None:
    """Attach CDP coverage tracking to one page."""
    cdp = await context.new_cdp_session(page)
    saver = SaveCoverage(cdp, plugin)
    _PAGE_COVERAGE_SAVERS[id(page)] = saver

    for method_name in ("reload", "goto", "go_back", "go_forward", "close"):
        _wrap_page_method(page, method_name, saver)

    await cdp.send("Profiler.enable")
    await cdp.send("Debugger.enable")
    await cdp.send(
        "Profiler.startPreciseCoverage", {"callCount": True, "detailed": True}
    )


async def _instrument_context(
    context,
    plugin: CoverageStore,
):
    """Patch a BrowserContext to auto-instrument pages for coverage."""
    instrumented_pages = []
    original_new_page = getattr(context, "new_page")
    original_close = getattr(context, "close")

    async def new_page(*args, **kwargs):
        page = await original_new_page(*args, **kwargs)
        await _instrument_page(context, page, plugin)
        instrumented_pages.append(page)
        return page

    async def close(*args, **kwargs):
        for page in list(instrumented_pages):
            await save_coverage(page)
            _clear_page_coverage_saver(page)
        return await original_close(*args, **kwargs)

    setattr(context, "new_page", new_page)
    setattr(context, "close", close)

    return context
