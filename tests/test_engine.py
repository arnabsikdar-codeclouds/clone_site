"""Tests for cloner.engine module."""

import asyncio
import os
import shutil
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from config import CloneConfig
from cloner.engine import CloneEngine
from cloner.models import CloneJob, JobStatus


@pytest.fixture
def config(tmp_path):
    return CloneConfig(
        output_dir=str(tmp_path),
        max_depth=2,
        max_pages=10,
        max_retries=1,
        retry_base_delay=0.01,
        respect_robots=False,
        verify_ssl=False,
    )


@pytest.fixture
def job():
    return CloneJob(job_id="test123", url="https://example.com/", domain="example.com")


class TestCloneEngine:
    @pytest.mark.asyncio
    async def test_basic_clone(self, config, job):
        """Test a basic single-page clone."""
        html = b"<html><head></head><body><h1>Hello</h1></body></html>"

        async def mock_fetch(url):
            if "robots.txt" in url:
                return (404, b"", "", None)
            return (200, html, "text/html", None)

        engine = CloneEngine(config)
        with patch.object(engine._downloader, 'start', new_callable=AsyncMock):
            with patch.object(engine._downloader, 'close', new_callable=AsyncMock):
                with patch.object(engine._downloader, 'fetch', side_effect=mock_fetch):
                    await engine.run(job)

        assert job.status == JobStatus.DONE
        assert job.pages_crawled >= 1
        assert job.output_path != ""

    @pytest.mark.asyncio
    async def test_cancellation(self, config, job):
        """Test that cancellation stops the engine."""
        call_count = 0
        html = b'<html><body><a href="/page2">Link</a></body></html>'

        async def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            # Cancel after first fetch
            if call_count >= 1:
                job.cancel_requested = True
            return (200, html, "text/html", None)

        engine = CloneEngine(config)
        with patch.object(engine._downloader, 'start', new_callable=AsyncMock):
            with patch.object(engine._downloader, 'close', new_callable=AsyncMock):
                with patch.object(engine._downloader, 'fetch', side_effect=mock_fetch):
                    await engine.run(job)

        assert job.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_error_collection(self, config, job):
        """Test that fetch errors are collected as ErrorDetail objects."""
        from cloner.models import ErrorDetail, ErrorCategory

        err = ErrorDetail(url="https://example.com/", category=ErrorCategory.TIMEOUT, message="timeout")

        async def mock_fetch(url):
            return (0, b"", "", err)

        engine = CloneEngine(config)
        with patch.object(engine._downloader, 'start', new_callable=AsyncMock):
            with patch.object(engine._downloader, 'close', new_callable=AsyncMock):
                with patch.object(engine._downloader, 'fetch', side_effect=mock_fetch):
                    await engine.run(job)

        assert len(job.errors) > 0
        assert job.errors[0].category == ErrorCategory.TIMEOUT

    @pytest.mark.asyncio
    async def test_site_size_computed(self, config, job):
        """Test that site_size_bytes is computed after save."""
        html = b"<html><head></head><body>Hello World</body></html>"

        async def mock_fetch(url):
            return (200, html, "text/html", None)

        engine = CloneEngine(config)
        with patch.object(engine._downloader, 'start', new_callable=AsyncMock):
            with patch.object(engine._downloader, 'close', new_callable=AsyncMock):
                with patch.object(engine._downloader, 'fetch', side_effect=mock_fetch):
                    await engine.run(job)

        assert job.status == JobStatus.DONE
        assert job.site_size_bytes > 0
