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
- Full VS Code integration: coverage gutters work for JS/TS files just for Python

## Limitations

### Requirements for use

You must implement your tests in Python using the async Playwright API with the Chrome
browser for this to work. For details, see the installation section.

### Loss of coverage data due to page navigation

Coverage collection is not perfect when doing page navigation. Coverage data is attached
to the currently executing page context. If that page reloads or navigates away before
`pytest-jscov` reads the coverage data, the old execution context is gone and its coverage
data with it.

We implement a partial workaround for this issue. When the plugin is active,
Playwright browser contexts created via `browser.new_context()` and pages
created via `browser.new_page()` are automatically instrumented so that
`reload`, `goto`, `go_back`, and `go_forward` flush coverage immediately
before those navigations run.

This improves coverage retention for navigations initiated through those page methods in
tests, but it does **not** catch page navigation triggered from JavaScript, such as

   `window.location.assign(...)`

For those cases, you can call `save_coverage(page)` just before the action that would
replace the page context:

```python
from pytest_jscov import save_coverage

await save_coverage(page)
await page.evaluate("window.location.assign('about:blank')")
```

### Detection of executable lines

We use a custom code to detect executable lines in JS/TS files to keep this project
lightweight. This code may not be perfect, if you encounter issues, drop an issue.

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

If you run `pytest --cov`, any page created from Playwright in Python will have its
coverage recorded. The methods `browser.new_context()` and `browser.new_page()`
return instrumented objects so that:

- **On each `context.new_page()`:** opens a CDP session and starts V8 precise
   coverage for the new page
- **During the page lifetime:** flushes coverage before `page.reload()`,
   `page.goto()`, `page.go_back()`, `page.go_forward()`, and `page.close()`
- **During the page lifetime:** lets you call `await save_coverage(page)` to
   persist coverage before JS-triggered navigation
- **On `page.close()` or `context.close()`:** collects coverage from all pages
   before closing the context

When `--cov` is not passed to pytest, Playwright is not instrumented.

If you want to use manual coverage saving, import it explicitly:

```python
from pytest_jscov import save_coverage
```

When `--cov` is not passed to pytest, `save_coverage` does nothing.

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

### Filtering

Just like with Python sources, you can restrict the coverage report to individual files or directories by passing a path to `--cov`, for example:

   ```bash
   pytest --cov=src/myapp/static/foo.js
   ```

## How it works

1. The **pytest plugin** (`pytest_jscov.plugin`) patches Playwright when
   `--cov` is active and uses a `pytest_runtestloop` hook to inject the
   accumulated JS/TS line hits directly into pytest-cov's active `Coverage`
   object before pytest-cov finalises the report.

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
