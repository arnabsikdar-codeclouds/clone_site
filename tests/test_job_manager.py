"""Tests for web.job_manager module."""

import time
import pytest

from config import CloneConfig
from cloner.models import CloneJob, JobStatus
from web.job_manager import JobManager


@pytest.fixture
def manager(tmp_path):
    config = CloneConfig(output_dir=str(tmp_path), job_ttl=10)
    return JobManager(config)


class TestJobManager:
    def test_create_job(self, manager):
        job = manager.create_job("https://example.com")
        assert job.job_id
        assert job.url == "https://example.com"
        assert job.domain == "example.com"
        assert job.created_at > 0

    def test_create_job_adds_scheme(self, manager):
        job = manager.create_job("example.com")
        assert job.url == "https://example.com"

    def test_get_job(self, manager):
        job = manager.create_job("https://example.com")
        found = manager.get_job(job.job_id)
        assert found is job

    def test_get_nonexistent_job(self, manager):
        assert manager.get_job("nonexistent") is None

    def test_list_jobs(self, manager):
        manager.create_job("https://a.com")
        manager.create_job("https://b.com")
        assert len(manager.list_jobs()) == 2

    def test_cancel_job(self, manager):
        job = manager.create_job("https://example.com")
        job.status = JobStatus.CRAWLING
        assert manager.cancel_job(job.job_id) is True
        assert job.cancel_requested is True

    def test_cancel_done_job_fails(self, manager):
        job = manager.create_job("https://example.com")
        job.status = JobStatus.DONE
        assert manager.cancel_job(job.job_id) is False

    def test_delete_job(self, manager):
        job = manager.create_job("https://example.com")
        assert manager.delete_job(job.job_id) is True
        assert manager.get_job(job.job_id) is None

    def test_delete_nonexistent_job(self, manager):
        assert manager.delete_job("nonexistent") is False

    def test_find_recent_clone(self, manager):
        job = manager.create_job("https://example.com/")
        job.status = JobStatus.DONE
        found = manager.find_recent_clone("https://example.com/")
        assert found is job

    def test_find_recent_clone_not_found(self, manager):
        assert manager.find_recent_clone("https://other.com") is None

    def test_cleanup_expired(self, manager):
        job = manager.create_job("https://example.com")
        job.status = JobStatus.DONE
        job.completed_at = time.time() - 20  # Older than TTL (10s)
        manager._cleanup_expired()
        assert manager.get_job(job.job_id) is None

    def test_cleanup_keeps_active_jobs(self, manager):
        job = manager.create_job("https://example.com")
        job.status = JobStatus.CRAWLING
        manager._cleanup_expired()
        assert manager.get_job(job.job_id) is not None
