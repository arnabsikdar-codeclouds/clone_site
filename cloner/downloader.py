import asyncio
import logging

import aiohttp

from config import CloneConfig

logger = logging.getLogger(__name__)


class Downloader:
    def __init__(self, config: CloneConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self._config.timeout)
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            headers={"User-Agent": self._config.user_agent},
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str) -> tuple[int, bytes, str]:
        """Download a URL. Returns (status_code, body, content_type).
        Retries once on 5xx or timeout."""
        for attempt in range(2):
            try:
                return await self._do_fetch(url)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == 0:
                    logger.debug("Retry %s after error: %s", url, e)
                    await asyncio.sleep(0.5)
                else:
                    logger.warning("Failed to fetch %s: %s", url, e)
                    return (0, b"", "")

    async def _do_fetch(self, url: str) -> tuple[int, bytes, str]:
        async with self._semaphore:
            async with self._session.get(url, allow_redirects=True, ssl=False) as resp:
                content_type = resp.headers.get("Content-Type", "")
                # Check content-length before reading
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > self._config.max_file_size:
                    logger.warning("Skipping %s — too large (%s bytes)", url, cl)
                    return (resp.status, b"", content_type)
                body = await resp.read()
                if len(body) > self._config.max_file_size:
                    logger.warning("Skipping %s — body too large (%d bytes)", url, len(body))
                    return (resp.status, b"", content_type)
                return (resp.status, body, content_type)
