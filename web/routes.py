import asyncio
import json
import logging
import os
import mimetypes
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from .schemas import CloneRequest, CloneResponse, JobResponse, ErrorDetailResponse
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
    warning = ""
    # Duplicate job detection (D2)
    existing = job_manager.find_recent_clone(req.url)
    if existing:
        warning = f"This URL was already cloned (job {existing.job_id}). Cloning again."

    job = job_manager.create_job(req.url, req.max_depth, req.max_pages)

    # Launch clone as background task
    asyncio.create_task(job_manager.start_clone(
        job,
        max_depth=req.max_depth,
        max_pages=req.max_pages,
        verify_ssl=req.verify_ssl,
        request_delay=req.request_delay,
        respect_robots=req.respect_robots,
        use_sitemap=req.use_sitemap,
        user_agent=req.user_agent,
        auth_cookies=req.auth_cookies,
        auth_headers=req.auth_headers,
        use_playwright=req.use_playwright,
    ))

    return CloneResponse(job_id=job.job_id, message="Clone started", warning=warning)


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


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    success = job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")
    return {"message": "Cancellation requested"}


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


@router.get("/site/{job_id}/{path:path}")
async def browse_site(job_id: str, path: str, request: Request):
    """Dedicated route for browsing cloned sites in a new tab.
    URL stays as /site/{job_id}/... so it doesn't collide with the app."""
    return await _serve_cloned_file(job_id, path, request, mode="browse")


@router.get("/api/jobs/{job_id}/browse/{path:path}")
async def browse_file(job_id: str, path: str, request: Request):
    """API browse endpoint — used by iframe preview (embed=1) and legacy links."""
    embed = request.query_params.get("embed") == "1"
    mode = "embed" if embed else "browse"
    return await _serve_cloned_file(job_id, path, request, mode=mode)


async def _serve_cloned_file(
    job_id: str, path: str, request: Request, mode: str = "browse",
):
    """Serve a file from a cloned site.
    mode: "browse" = new-tab browsing, "embed" = iframe preview."""
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

    # For HTML files, inject <base> tag so relative URLs resolve correctly.
    if content_type and "html" in content_type:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        # Determine the base path depending on which route served this
        # /site/{job_id}/  or  /api/jobs/{job_id}/browse/
        if request.url.path.startswith("/site/"):
            browse_base = f"/site/{job_id}/"
        else:
            browse_base = f"/api/jobs/{job_id}/browse/"

        # Build the path relative to the browse root for sub-pages
        rel_dir = os.path.relpath(os.path.dirname(file_path), job.output_path).replace("\\", "/")
        if rel_dir and rel_dir != ".":
            browse_base += rel_dir + "/"

        inject = f'<base href="{browse_base}">'

        # SPA routers (React Router, Vue Router) read window.location.pathname
        # directly to decide which route to render. The actual URL like
        # /site/{job_id}/index.html won't match SPA routes like "/" and the
        # app shows its own 404 page.
        #
        # Fix: replaceState to "/" so SPA routing works correctly. The <base>
        # tag still resolves relative asset URLs (JS, CSS, images) to the
        # correct /site/{job_id}/... paths. We put the job_id in a hash
        # fragment so the URL bar shows /#site_{job_id} for identification.
        inject += (
            f'<script>history.replaceState(null,"","/#site_{job_id}");</script>'
        )

        if mode == "embed":
            # Neutralize frame-busting scripts: override top/parent references
            # so cloned JS cannot navigate the iframe away (which causes 404).
            inject += (
                "<script>"
                "Object.defineProperty(window,'top',{get:function(){return window}});"
                "Object.defineProperty(window,'parent',{get:function(){return window}});"
                "</script>"
            )

            # Strip existing X-Frame-Options / frame-deny meta tags
            html = re.sub(
                r'<meta[^>]*http-equiv\s*=\s*["\']?X-Frame-Options["\']?[^>]*>',
                '', html, flags=re.IGNORECASE,
            )

        # Insert after <head> or at the top of the document
        if re.search(r"<head[^>]*>", html, re.IGNORECASE):
            html = re.sub(r"(<head[^>]*>)", r"\1" + inject, html, count=1, flags=re.IGNORECASE)
        else:
            html = inject + html

        headers = {}
        if mode == "embed":
            headers["X-Frame-Options"] = "SAMEORIGIN"
            headers["Content-Security-Policy"] = "frame-ancestors 'self'"

        return HTMLResponse(content=html, media_type="text/html", headers=headers)

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
        errors=[
            ErrorDetailResponse(
                url=e.url, category=e.category.value,
                message=e.message, status_code=e.status_code,
            )
            for e in job.errors
        ],
        site_size_bytes=job.site_size_bytes,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
