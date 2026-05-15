"""Tests for cloner.downloader module."""

import asyncio
import pytest
import aiohttp
from unittest.mock import AsyncMock, patch, MagicMock

from config import CloneConfig
from cloner.downloader import Downloader, RateLimiter
from cloner.models import ErrorCategory


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_no_delay(self):
        limiter = RateLimiter(0.0)
        # Should return immediately
        await limiter.acquire("example.com")

    @pytest.mark.asyncio
    async def test_delay_enforced(self):
        limiter = RateLimiter(0.1)
        import time
        start = time.monotonic()
        await limiter.acquire("example.com")
        await limiter.acquire("example.com")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08  # Allow small tolerance


class TestDownloader:
    @pytest.mark.asyncio
    async def test_fetch_returns_error_detail_on_timeout(self):
        config = CloneConfig(timeout=1, max_retries=1, retry_base_delay=0.01)
        dl = Downloader(config)

        with patch.object(dl, '_do_fetch', side_effect=asyncio.TimeoutError()):
            await dl.start()
            status, body, ct, err = await dl.fetch("https://example.com/timeout")
            await dl.close()

        assert status == 0
        assert err is not None
        assert err.category == ErrorCategory.TIMEOUT

    @pytest.mark.asyncio
    async def test_fetch_returns_error_on_connection_error(self):
        config = CloneConfig(timeout=1, max_retries=1, retry_base_delay=0.01)
        dl = Downloader(config)

        with patch.object(dl, '_do_fetch', side_effect=aiohttp.ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("Connection refused")
        )):
            await dl.start()
            status, body, ct, err = await dl.fetch("https://example.com/fail")
            await dl.close()

        assert status == 0
        assert err is not None

    @pytest.mark.asyncio
    async def test_fetch_retries_on_5xx(self):
        config = CloneConfig(timeout=5, max_retries=3, retry_base_delay=0.01)
        dl = Downloader(config)

        call_count = 0
        async def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return (500, b"error", "text/plain")
            return (200, b"ok", "text/html")

        with patch.object(dl, '_do_fetch', side_effect=mock_fetch):
            await dl.start()
            status, body, ct, err = await dl.fetch("https://example.com/retry")
            await dl.close()

        assert status == 200
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        config = CloneConfig(timeout=5, max_retries=1)
        dl = Downloader(config)

        async def mock_fetch(url):
            return (200, b"<html>test</html>", "text/html")

        with patch.object(dl, '_do_fetch', side_effect=mock_fetch):
            await dl.start()
            status, body, ct, err = await dl.fetch("https://example.com/")
            await dl.close()

        assert status == 200
        assert body == b"<html>test</html>"
        assert err is None
