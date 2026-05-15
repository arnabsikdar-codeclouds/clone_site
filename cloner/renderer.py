"""Optional Playwright-based SPA renderer for JavaScript-heavy sites."""

import logging
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
