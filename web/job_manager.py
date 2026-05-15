import asyncio
import json
import logging
import os
import shutil
import uuid
import zipfile
from typing import Any
from urllib.parse import urlparse

from config import CloneConfig
from cloner.models import CloneJob, JobStatus
from cloner.engine import CloneEngine

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, config: CloneConfig) -> None:
        self._config = config
        self._jobs: dict[str, CloneJob] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._zip_cache: dict[str, str] = {}  # job_id -> zip path

    def create_job(self, url: str, max_depth: int | None = None, max_pages: int | None = None) -> CloneJob:
        job_id = uuid.uuid4().hex[:12]
        parsed = urlparse(url)
        domain = parsed.hostname or "unknown"

        # Ensure URL has scheme
        if not parsed.scheme:
            url = "https://" + url
            parsed = urlparse(url)
            domain = parsed.hostname or "unknown"

        job = CloneJob(job_id=job_id, url=url, domain=domain)
        self._jobs[job_id] = job
        self._subscribers[job_id] = []
        return job

    def get_job(self, job_id: str) -> CloneJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[CloneJob]:
        return list(self._jobs.values())

    def subscribe(self, job_id: str) -> asyncio.Queue | None:
        if job_id not in self._subscribers:
            return None
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        if job_id in self._subscribers:
            try:
                self._subscribers[job_id].remove(q)
            except ValueError:
                pass

    async def _broadcast(self, job_id: str, data: dict[str, Any]) -> None:
        if job_id in self._subscribers:
            for q in self._subscribers[job_id]:
                await q.put(data)

    async def start_clone(self, job: CloneJob, max_depth: int | None = None, max_pages: int | None = None) -> None:
        config = CloneConfig(
            max_depth=max_depth or self._config.max_depth,
            max_pages=max_pages or self._config.max_pages,
            concurrency=self._config.concurrency,
            timeout=self._config.timeout,
            max_file_size=self._config.max_file_size,
            user_agent=self._config.user_agent,
            output_dir=self._config.output_dir,
        )
        engine = CloneEngine(config)

        async def on_progress(data: dict[str, Any]) -> None:
            await self._broadcast(job.job_id, data)

        try:
            await engine.run(job, progress=on_progress)
        finally:
            # Send terminal event
            await self._broadcast(job.job_id, {"type": "end", "status": job.status.value})

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and its output files from disk."""
        job = self._jobs.get(job_id)
        if not job:
            return False

        # Remove output directory
        if job.output_path and os.path.isdir(job.output_path):
            shutil.rmtree(job.output_path, ignore_errors=True)

        # Remove cached ZIP
        if job_id in self._zip_cache:
            zip_path = self._zip_cache.pop(job_id)
            if os.path.exists(zip_path):
                os.remove(zip_path)

        # Clean up subscribers
        self._subscribers.pop(job_id, None)

        # Remove job record
        del self._jobs[job_id]
        return True

    def get_zip_path(self, job: CloneJob) -> str | None:
        """Generate or return cached ZIP for a completed job."""
        if job.status != JobStatus.DONE or not job.output_path:
            return None

        if job.job_id in self._zip_cache:
            path = self._zip_cache[job.job_id]
            if os.path.exists(path):
                return path

        zip_path = job.output_path.rstrip("/\\") + ".zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(job.output_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(job.output_path))
                        zf.write(file_path, arcname)
            self._zip_cache[job.job_id] = zip_path
            return zip_path
        except Exception as e:
            logger.error("Failed to create ZIP: %s", e)
            return None
