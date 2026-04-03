# pytest-jscov

Get a single, unified coverage report for your full-stack Python + JS/TS application.

This pytest plugin collects JavaScript and TypeScript code coverage from
[Playwright](https://playwright.dev/python/) browser tests via Chrome's DevTools Protocol
(CDP) and merges it into [pytest-cov](https://github.com/pytest-dev/pytest-cov)'s combined
report. In other words, we use Chrome's profiler to track which lines of code were executed.

Using pytest-jscov is perfect if you write your frontend tests in Python with Playwright
already. Then you get coverage measurements on top with almost no extra effort.

## Features

- Collects V8 precise coverage from Chromium-based browsers via CDP
- Resolves inline sourcemaps (e.g. from esbuild) to map coverage back to
  original `.ts` source files
- Merges JS/TS line hits into pytest-cov so everything appears in one report
- Works with `--cov-branch`, but no branch coverage is collected
- Zero-config when coverage is not active: the `jscov` fixture is a no-op
  unless `--cov` is passed
- Full VS Code integration: coverage gutters work for JS/TS files just for Python

## Limitations

### Requirements for use

You must implement your tests in Python using the async Playwright API with the Chrome
browser for this to work. For details, see the installation section.

### Loss of coverage data due to page navigation

Coverage collection is not perfect when doing page nagivation. Coverage data is attached
to the currently executing page context. If that page reloads or navigates away before
`pytest-jscov` reads the coverage data, the old execution context is gone and its coverage
data with it.

We implement a partial workaround for this issue. While the `jscov(...)` context is
active, it temporarily wraps the active Playwright `Page` object's `reload`, `goto`,
`go_back`, and `go_forward` methods and flushes coverage immediately before those
navigations run.

This improves coverage retention for navigations initiated through those page methods in
tests, but it does **not** catch page navigation triggered from JavaScript, such as

   `window.location.assign(...)`

### Detection of executable lines

We use a custom code to detect executable lines in JS/TS files to keep this project
lightweight. This code may not be perfect yet, if you encounter issues, drop an issue.

## Installation

```bash
pip install pytest-jscov
```

The plugin requires `pytest`, `pytest-cov`, and `playwright` (with Chromium installed).

### Register the coverage.py plugin

In your `pyproject.toml`:

```toml
[tool.coverage.run]
plugins = ["pytest_jscov.covplugin"]

[tool.coverage.pytest_jscov.covplugin]
static_root = "src/myapp/static"
```

`static_root` tells the plugin where your JS/TS source files live on disk, so
it can match coverage data to real files.

The plugin automatically switches `coverage.py` to the plugin-compatible tracing
`ctrace` core.

### Use the `jscov` fixture in your page fixture

```python
import pytest
from collections.abc import AsyncIterator
from playwright.async_api import Browser, Page

@pytest.fixture
async def page(browser: Browser, jscov) -> AsyncIterator[Page]:
    context = await browser.new_context()
    page = await context.new_page()

    async with jscov(context, page, "http://localhost:8000"):
        await page.goto("http://localhost:8000")
        yield page

    await page.close()
    await context.close()
```

The `jscov(context, page, base_url)` call returns an async context manager
that:

- **On enter:** opens a CDP session and starts V8 precise coverage
- **During the context:** flushes coverage before `page.reload()`,
   `page.goto()`, `page.go_back()`, and `page.go_forward()`
- **On exit:** collects coverage, fetches script sources, and records
  everything

When `--cov` is not passed to pytest, `jscov` is a no-op context manager, so
you don't need any `if` guards.

### Run your tests

```bash
pytest --cov=src --cov-report=term
```

JS and TS files appear alongside Python in the coverage report:

```
Name                                  Stmts   Miss  Cover
----------------------------------------------------------
src/myapp/main.py                       180     90    50%
src/myapp/static/app.js                 441    144    67%
src/myapp/static/modules/foo.ts         194     14    93%
src/myapp/static/modules/bar.js         103     10    90%
----------------------------------------------------------
TOTAL                                   918    258    72%
```

## Configuration

### `static_root` (required)

This is the filesystem path to your static files directory. Can be set in two ways:

1. **coverage.py config** (recommended):

   ```toml
   [tool.coverage.pytest_jscov.covplugin]
   static_root = "src/myapp/static"
   ```

2. **CLI option:**

   ```bash
   pytest --cov=src --jscov=src/myapp/static
   ```

   The CLI option takes precedence over the config file.

### Filtering

Just like with Python sources, you can restrict the coverage report to individual files or directories by passing a path to `--cov`, for example:

   ```bash
   pytest --cov=src/myapp/static/foo.js
   ```

## How it works

1. The **pytest plugin** (`pytest_jscov.plugin`) provides the `jscov` fixture
   and a `pytest_runtestloop` hook. During each test, coverage entries from V8
   are accumulated in memory. After all tests complete, the accumulated data is
   written as a `.coverage.jscov` file that pytest-cov's `combine()` step picks
   up automatically.

2. The **coverage.py plugin** (`pytest_jscov.covplugin`) registers a file
   tracer and file reporter for JS/TS files. This teaches coverage.py how to
   find, read, and report on JavaScript and TypeScript source files.

### Sourcemap support

When a script contains an inline sourcemap
(`//# sourceMappingURL=data:application/json;base64,...`), the plugin decodes
the VLQ mappings and attributes coverage to the original source files. This
means if you use a bundler like esbuild to transpile TypeScript with
`--sourcemap=inline`, coverage is reported against your `.ts` files, not the
generated `.js`.

### IDE integration

When using the
[Python Testing](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
extension in VS Code, coverage gutters work for JS/TS files just like they do
for Python. VS Code runs pytest with `--cov --cov-branch` automatically, and
the merged report includes your frontend files — you'll see green/red line
markers directly in your `.ts` and `.js` sources.
