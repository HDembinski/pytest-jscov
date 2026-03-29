"""Inner test exercising the jscov fixture with async Playwright."""

import pytest

from pytest_jscov.plugin import JsCovPlugin


def _hit_delta(
    before: dict[int, int], after: dict[int, int], lines: set[int]
) -> dict[int, int]:
    return {line: after.get(line, 0) - before.get(line, 0) for line in lines}


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

    assert {1, 2, 3, 4, 5, 7} == covered, f"expected line 4 covered, got {hits}"
    assert {6} == uncovered, f"expected line 1 uncovered, got {hits}"


@pytest.mark.anyio
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
    request, browser, jscov, base_url, navigation_method
):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)

    before = dict(plugin.accumulated.get("/static/app.js", {}))
    second_url = f"{base_url}/?page=second"

    context = await browser.new_context()
    page = await context.new_page()

    # set up a bit of history for the back/forward tests
    await page.goto(second_url)
    await page.goto(base_url)
    await page.goto(second_url)
    await page.go_back()

    async with jscov(context, page, base_url):
        assert await page.evaluate("greet('Alice')") == "Hi, Alice"

        if navigation_method == "reload":
            await page.reload()
        elif navigation_method == "goto":
            await page.goto(second_url)
        elif navigation_method == "go_back":
            await page.go_back()
        elif navigation_method == "go_forward":
            await page.go_forward()

        assert await page.evaluate("greet()") == "Hi, stranger"

    await page.close()
    await context.close()

    after = plugin.accumulated["/static/app.js"]
    delta = _hit_delta(before, after, {4, 6})

    assert delta[4] == 1, (
        f"expected truthy branch hit before {navigation_method}, got {delta}"
    )
    assert delta[6] == 1, (
        f"expected falsy branch hit after {navigation_method}, got {delta}"
    )
