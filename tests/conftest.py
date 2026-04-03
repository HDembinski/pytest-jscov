import functools
import http.server
import threading
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

collect_ignore = ["smoke"]

DATA_DIR = Path(__file__).parent / "data"


# Keep this at session scope because the shared async browser fixture is also
# session-scoped; AnyIO raises ScopeMismatch if the backend fixture is narrower.
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
async def browser():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        yield browser
        await browser.close()
