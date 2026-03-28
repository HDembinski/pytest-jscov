import functools
import http.server
import threading
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session")
def anyio_backend():
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
    async with async_playwright() as p:
        b = await p.chromium.launch()
        yield b
        await b.close()
