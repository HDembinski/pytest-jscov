"""Inner test exercising the jscov fixture with async Playwright."""

import pytest

from pytest_jscov.plugin import JsCovPlugin


@pytest.mark.anyio
async def test_js_coverage(request, browser, jscov, base_url):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    context = await browser.new_context()
    page = await context.new_page()

    async with jscov(context, page, base_url):
        await page.goto(base_url)
        assert await page.evaluate("greet('Alice')") == "Hi, Alice"

    await page.close()
    await context.close()

    # After the jscov context exits, coverage is accumulated in the plugin.
    assert "/static/app.js" in plugin.accumulated
    hits = plugin.accumulated["/static/app.js"]

    #   1: // this function should be covered by tests
    #   2: function greet(name) {   ← covered
    #   3:   if (name) {            ← covered
    #   4:     return "Hi, " + name ← covered
    #   5:   }
    #   6:   return "Hi, stranger"  ← NOT covered
    #   7: }
    covered = {line for line, count in hits.items() if count > 0}
    uncovered = {line for line, count in hits.items() if count == 0}

    assert 4 in covered, f"expected line 4 covered, got {hits}"
    assert 6 in uncovered, f"expected line 1 uncovered, got {hits}"
