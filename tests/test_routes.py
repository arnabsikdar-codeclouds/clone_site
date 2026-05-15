"""Tests for web.routes module."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestRoutes:
    def test_list_jobs(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_job(self, client):
        resp = client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404

    def test_cancel_nonexistent_job(self, client):
        resp = client.post("/api/jobs/nonexistent/cancel")
        assert resp.status_code == 400

    def test_delete_nonexistent_job(self, client):
        resp = client.delete("/api/jobs/nonexistent")
        assert resp.status_code == 404

    def test_download_nonexistent_job(self, client):
        resp = client.get("/api/jobs/nonexistent/download")
        assert resp.status_code == 404

    def test_browse_nonexistent_job(self, client):
        resp = client.get("/api/jobs/nonexistent/browse/index.html")
        assert resp.status_code == 404

    def test_clone_creates_job(self, client):
        resp = client.post("/api/clone", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["message"] == "Clone started"

    def test_clone_missing_url(self, client):
        resp = client.post("/api/clone", json={})
        assert resp.status_code == 422  # validation error

    def test_path_traversal_protection(self, client):
        """Test that path traversal is blocked on both browse routes."""
        # First create a job
        resp = client.post("/api/clone", json={"url": "https://example.com"})
        job_id = resp.json()["job_id"]

        # Try path traversal on API browse route
        resp = client.get(f"/api/jobs/{job_id}/browse/../../etc/passwd")
        assert resp.status_code in (403, 404)

        # Try path traversal on /site/ route
        resp = client.get(f"/site/{job_id}/../../etc/passwd")
        assert resp.status_code in (403, 404)
