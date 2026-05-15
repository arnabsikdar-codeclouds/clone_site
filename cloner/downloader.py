import asyncio
import logging
import random
import time
from urllib.parse import urlparse

import aiohttp
from yarl import URL

from config import CloneConfig
from .models import ErrorCategory, ErrorDetail

logger = logging.getLogger(__name__)


class RateLimiter:
    """Per-domain rate limiter using asyncio.Lock + timestamp tracking."""

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    async def acquire(self, domain: str) -> None:
        if self._delay <= 0:
            return
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            wait = self._delay - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[domain] = time.monotonic()


class Downloader:
    def __init__(self, config: CloneConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(config.request_delay)

    async def start(self, target_url: str = "") -> None:
        timeout = aiohttp.ClientTimeout(total=self._config.timeout)
        headers = {
            "User-Agent": self._config.user_agent,
            "Accept-Encoding": "gzip, deflate, br",
        }
        # Merge custom auth headers
        if self._config.auth_headers:
            headers.update(self._config.auth_headers)

        connector = aiohttp.TCPConnector(
            ssl=None if self._config.verify_ssl else False,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            connector=connector,
        )
        # Pre-load auth cookies with proper domain association
        if self._config.auth_cookies:
            response_url = URL(target_url) if target_url else None
            self._session.cookie_jar.update_cookies(
                self._config.auth_cookies, response_url=response_url,
            )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str) -> tuple[int, bytes, str, ErrorDetail | None]:
        """Download a URL. Returns (status_code, body, content_type, error_detail).
        Retries with exponential backoff on transient errors."""
        return await self._fetch_inner(url)

    async def fetch_with_final_url(self, url: str) -> tuple[int, bytes, str, str, ErrorDetail | None]:
        """Like fetch() but also returns the final URL after redirects.
        Returns (status_code, body, content_type, final_url, error_detail)."""
        return await self._fetch_inner(url, return_final_url=True)

    async def _fetch_inner(self, url: str, return_final_url: bool = False):
        max_retries = self._config.max_retries
        base_delay = self._config.retry_base_delay

        last_error: ErrorDetail | None = None
        for attempt in range(max_retries):
            try:
                status, body, ct, final_url = await self._do_fetch(url)
                # Retry on 5xx
                if status >= 500 and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.debug("Retry %s (attempt %d) after %d status", url, attempt + 1, status)
                    await asyncio.sleep(delay)
                    last_error = ErrorDetail(
                        url=url, category=ErrorCategory.HTTP_ERROR,
                        message=f"HTTP {status}", status_code=status,
                    )
                    continue
                if return_final_url:
                    return (status, body, ct, final_url, None)
                return (status, body, ct, None)

            except asyncio.TimeoutError:
                last_error = ErrorDetail(
                    url=url, category=ErrorCategory.TIMEOUT,
                    message="Request timed out",
                )
            except aiohttp.ClientConnectorCertificateError as e:
                last_error = ErrorDetail(
                    url=url, category=ErrorCategory.SSL_ERROR,
                    message=str(e),
                )
            except aiohttp.ClientConnectorError as e:
                msg = str(e)
                cat = ErrorCategory.DNS_FAILURE if "Name or service not known" in msg or "getaddrinfo" in msg else ErrorCategory.UNKNOWN
                last_error = ErrorDetail(url=url, category=cat, message=msg)
            except aiohttp.ClientSSLError as e:
                last_error = ErrorDetail(
                    url=url, category=ErrorCategory.SSL_ERROR,
                    message=str(e),
                )
            except aiohttp.ClientError as e:
                last_error = ErrorDetail(
                    url=url, category=ErrorCategory.UNKNOWN,
                    message=str(e),
                )

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.debug("Retry %s (attempt %d) after error: %s", url, attempt + 1, last_error.message)
                await asyncio.sleep(delay)
            else:
                logger.warning("Failed to fetch %s after %d attempts: %s", url, max_retries, last_error.message)

        if return_final_url:
            return (0, b"", "", "", last_error)
        return (0, b"", "", last_error)

    async def _do_fetch(self, url: str) -> tuple[int, bytes, str, str]:
        """Returns (status, body, content_type, final_url)."""
        # Rate limit per domain
        domain = urlparse(url).hostname or ""
        await self._rate_limiter.acquire(domain)

        async with self._semaphore:
            async with self._session.get(url, allow_redirects=True) as resp:
                content_type = resp.headers.get("Content-Type", "")
                final_url = str(resp.url)
                # Check content-length before reading
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > self._config.max_file_size:
                    logger.warning("Skipping %s -- too large (%s bytes)", url, cl)
                    return (resp.status, b"", content_type, final_url)
                body = await resp.read()
                if len(body) > self._config.max_file_size:
                    logger.warning("Skipping %s -- body too large (%d bytes)", url, len(body))
                    return (resp.status, b"", content_type, final_url)
                return (resp.status, body, content_type, final_url)
