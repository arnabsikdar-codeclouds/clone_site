"""Optional Playwright-based SPA renderer for JavaScript-heavy sites."""

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


def is_playwright_available() -> bool:
    return _PLAYWRIGHT_AVAILABLE


class PlaywrightRenderer:
    """Headless Chromium renderer that intercepts network requests."""

    def __init__(self, user_agent: str = "") -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Install it with: "
                "pip install playwright && python -m playwright install chromium"
            )
        self._user_agent = user_agent
        self._playwright: Any = None
        self._browser: Any = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        launch_args = {"headless": True}
        self._browser = await self._playwright.chromium.launch(**launch_args)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def render(self, url: str, timeout: int = 30000) -> tuple[str, list[str]]:
        """Render a page and return (html_content, intercepted_asset_urls).

        Returns the fully rendered HTML after JavaScript execution,
        plus a list of asset URLs the page requested during loading.
        """
        intercepted_urls: list[str] = []

        context_opts: dict[str, Any] = {}
        if self._user_agent:
            context_opts["user_agent"] = self._user_agent

        context = await self._browser.new_context(**context_opts)
        page = await context.new_page()

        def on_request(request):
            req_url = request.url
            resource = request.resource_type
            if resource in ("stylesheet", "image", "font", "media", "script"):
                intercepted_urls.append(req_url)

        page.on("request", on_request)

        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout)
            html = await page.content()
            return html, intercepted_urls
        finally:
            await context.close()


class ThreadedPlaywrightRenderer:
    """Playwright renderer that runs in a dedicated thread.

    Works around the Windows limitation where uvicorn's event loop
    does not support asyncio.subprocess_exec (NotImplementedError).
    Playwright is started in a separate thread with its own event loop,
    and render() bridges calls from the caller's loop via futures.
    """

    def __init__(self, user_agent: str = "",
                 cookies: dict[str, str] | None = None,
                 target_url: str = "") -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Install it with: "
                "pip install playwright && python -m playwright install chromium"
            )
        self._user_agent = user_agent
        self._cookies = cookies or {}
        self._target_url = target_url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def start(self) -> None:
        """Start the background thread and wait for Playwright to be ready."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Wait for Playwright to initialize in the background thread
        await asyncio.get_event_loop().run_in_executor(None, self._ready.wait)

    def _run_loop(self) -> None:
        """Thread entry: create event loop, start Playwright, run forever."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._init_playwright())
        self._ready.set()
        self._loop.run_forever()
        # Cleanup after loop stops
        self._loop.run_until_complete(self._cleanup_playwright())
        self._loop.close()

    async def _init_playwright(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        # Create a persistent context with cookies pre-loaded
        context_opts: dict[str, Any] = {}
        if self._user_agent:
            context_opts["user_agent"] = self._user_agent
        self._context = await self._browser.new_context(**context_opts)
        # Inject auth cookies
        if self._cookies and self._target_url:
            from urllib.parse import urlparse
            parsed = urlparse(self._target_url)
            domain = parsed.hostname or ""
            pw_cookies = [
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                }
                for name, value in self._cookies.items()
            ]
            await self._context.add_cookies(pw_cookies)
            logger.info("ThreadedRenderer: injected %d cookies for %s", len(pw_cookies), domain)

    async def _cleanup_playwright(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def close(self) -> None:
        """Stop the background loop and thread."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)

    async def render(self, url: str, timeout: int = 30000) -> tuple[str, list[str]]:
        """Render a page in the background thread. Safe to call from any loop."""
        future = asyncio.run_coroutine_threadsafe(
            self._do_render(url, timeout), self._loop
        )
        # Wait for result without blocking the caller's event loop
        return await asyncio.wrap_future(future)

    async def _do_render(self, url: str, timeout: int) -> tuple[str, list[str]]:
        intercepted_urls: list[str] = []
        page = await self._context.new_page()

        def on_request(request):
            resource = request.resource_type
            if resource in ("stylesheet", "image", "font", "media", "script"):
                intercepted_urls.append(request.url)

        page.on("request", on_request)

        try:
            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout)
            except Exception:
                # networkidle may time out on long-polling sites;
                # fall back to whatever has loaded so far.
                pass
            html = await page.content()
            return html, intercepted_urls
        finally:
            await page.close()
