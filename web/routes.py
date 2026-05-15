import asyncio
import json
import logging
import os
import mimetypes
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from .schemas import CloneRequest, CloneResponse, JobResponse
from .job_manager import JobManager

logger = logging.getLogger(__name__)

router = APIRouter()

# Will be set by app.py
job_manager: JobManager | None = None


def init_routes(manager: JobManager) -> None:
    global job_manager
    job_manager = manager


@router.post("/api/clone", response_model=CloneResponse)
async def start_clone(req: CloneRequest) -> CloneResponse:
    job = job_manager.create_job(req.url, req.max_depth, req.max_pages)

    # Launch clone as background task
    asyncio.create_task(job_manager.start_clone(job, req.max_depth, req.max_pages))

    return CloneResponse(job_id=job.job_id, message="Clone started")


@router.get("/api/jobs")
async def list_jobs() -> list[JobResponse]:
    jobs = job_manager.list_jobs()
    return [_job_to_response(j) for j in jobs]


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JobResponse:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = job_manager.subscribe(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("type") == "end":
                        break
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"
        finally:
            job_manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/jobs/{job_id}/download")
async def download_zip(job_id: str) -> FileResponse:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    zip_path = job_manager.get_zip_path(job)
    if not zip_path:
        raise HTTPException(status_code=400, detail="Job not complete or ZIP generation failed")

    filename = f"{job.domain}.zip"
    return FileResponse(zip_path, filename=filename, media_type="application/zip")


@router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_manager.delete_job(job_id)
    return {"message": "Job deleted"}


@router.get("/api/jobs/{job_id}/browse/{path:path}")
async def browse_file(job_id: str, path: str, request: Request):
    job = job_manager.get_job(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Job not found")

    # Path traversal protection
    file_path = os.path.normpath(os.path.join(job.output_path, path))
    if not file_path.startswith(os.path.normpath(job.output_path)):
        raise HTTPException(status_code=403, detail="Access denied")

    # If path points to directory, serve index.html
    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, "index.html")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(file_path)

    # For HTML files, inject <base> tag and history.replaceState so SPA routers
    # see "/" as the pathname instead of the browse endpoint path.
    if content_type and "html" in content_type:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        browse_base = f"/api/jobs/{job_id}/browse/"
        # Build the path relative to the browse root for sub-pages
        rel_dir = os.path.relpath(os.path.dirname(file_path), job.output_path).replace("\\", "/")
        if rel_dir and rel_dir != ".":
            browse_base += rel_dir + "/"

        inject = (
            f'<base href="{browse_base}">'
            '<script>history.replaceState(null,"","/");</script>'
        )
        # Insert after <head> or at the top of the document
        if re.search(r"<head[^>]*>", html, re.IGNORECASE):
            html = re.sub(r"(<head[^>]*>)", r"\1" + inject, html, count=1, flags=re.IGNORECASE)
        else:
            html = inject + html

        return HTMLResponse(content=html, media_type="text/html")

    return FileResponse(file_path, media_type=content_type)


def _job_to_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        url=job.url,
        domain=job.domain,
        status=job.status.value,
        pages_crawled=job.pages_crawled,
        assets_downloaded=job.assets_downloaded,
        errors_count=len(job.errors),
        error_message=job.error_message,
    )
