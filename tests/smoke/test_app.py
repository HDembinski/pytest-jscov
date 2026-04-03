"""
Inner test exercising automatic Playwright instrumentation.

To run this test correctly, you must use `pytest tests/smoke/test_app.py --cov`.
"""

import pytest

from pytest_jscov import save_coverage
from pytest_jscov.plugin import JsCovPlugin


async def test_js_coverage(request, browser, base_url):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    context = await browser.new_context()
    page = await context.new_page()

    await page.goto(base_url)
    assert await page.evaluate("greet('Alice')") == "Hi, Alice"

    await page.close()
    await context.close()

    # After the jscov context exits, coverage is accumulated in the plugin.
    assert "/static/app.js" in plugin.accumulated
    hits = plugin.accumulated["/static/app.js"]

    #   1: // this function...      ← IGNORED
    #   2: function greet(name) {   ← covered
    #   3:   if (name) {            ← covered
    #   4:     return "Hi, " + name ← covered
    #   5:   }                      ← IGNORED
    #   6:   return "Hi, stranger"  ← NOT covered
    #   7: }                        ← IGNORED
    covered = {line for line, count in hits.items() if count > 0}
    uncovered = {line for line, count in hits.items() if count == 0}

    assert {2, 3, 4} == covered, f"expected truthy path covered, got {hits}"
    assert {6} == uncovered, f"expected falsy return uncovered, got {hits}"


async def test_manual_save_preserves_coverage_before_js_navigation(
    request, browser, base_url
):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    context = await browser.new_context()
    page = await context.new_page()

    await page.goto(base_url)
    assert await page.evaluate("greet('Alice')") == "Hi, Alice"

    await save_coverage(page)
    await page.evaluate("window.location.assign('about:blank')")
    await page.wait_for_url("about:blank")

    await page.close()
    await context.close()

    assert "/static/app.js" in plugin.accumulated
    hits = plugin.accumulated["/static/app.js"]
    covered = {line for line, count in hits.items() if count > 0}
    uncovered = {line for line, count in hits.items() if count == 0}

    assert {2, 3, 4} == covered, f"expected truthy path covered, got {hits}"
    assert {6} == uncovered, f"expected falsy return uncovered, got {hits}"


async def test_browser_new_page_is_instrumented(request, browser, base_url):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    page = await browser.new_page()

    await page.goto(base_url)
    assert await page.evaluate("greet('Alice')") == "Hi, Alice"

    await page.close()

    assert "/static/app.js" in plugin.accumulated
    hits = plugin.accumulated["/static/app.js"]
    covered = {line for line, count in hits.items() if count > 0}
    uncovered = {line for line, count in hits.items() if count == 0}

    assert {2, 3, 4} == covered, f"expected truthy path covered, got {hits}"
    assert {6} == uncovered, f"expected falsy return uncovered, got {hits}"


@pytest.mark.parametrize(
    "navigation_method",
    [
        "reload",
        "goto",
        "go_back",
        "go_forward",
    ],
)
async def test_page_navigation_preserves_prenavigation_coverage(
    request, browser, base_url, navigation_method
):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    second_url = f"{base_url}/?page=second"

    context = await browser.new_context()
    page = await context.new_page()

    # set up a bit of history for the back/forward tests
    await page.goto(second_url)
    await page.goto(base_url)
    await page.goto(second_url)
    await page.go_back()

    assert "/static/app.js" in plugin.accumulated
    setup_hits = plugin.accumulated["/static/app.js"]
    assert not {line for line, count in setup_hits.items() if count > 0}

    assert await page.evaluate("greet('Alice')") == "Hi, Alice"

    if navigation_method == "reload":
        await page.reload()
    elif navigation_method == "goto":
        await page.goto(second_url)
    elif navigation_method == "go_back":
        await page.go_back()
    elif navigation_method == "go_forward":
        await page.go_forward()

    before = plugin.accumulated["/static/app.js"]

    assert await page.evaluate("greet()") == "Hi, stranger"

    await page.close()
    await context.close()
    after = plugin.accumulated["/static/app.js"]

    assert {k for k, v in before.items() if v > 0} == {2, 3, 4}
    assert {k for k, v in after.items() if v > 0} == {2, 3, 4, 6}
