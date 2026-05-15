import asyncio
import logging
import os
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

import aiofiles

from config import CloneConfig
from .models import (
    CloneJob, Asset, AssetType, JobStatus, ErrorCategory, ErrorDetail,
    ProgressCallback,
)
from .url_utils import normalize_url, is_same_domain, url_to_local_path, classify_url
from .downloader import Downloader
from .parser import parse_html, parse_css
from .rewriter import rewrite_html, rewrite_css
from .encoding import decode_content
from .robots import RobotsChecker
from .renderer import is_playwright_available, PlaywrightRenderer, ThreadedPlaywrightRenderer

logger = logging.getLogger(__name__)


class CloneEngine:
    def __init__(self, config: CloneConfig) -> None:
        self._config = config
        self._downloader = Downloader(config)

    async def run(self, job: CloneJob, progress: ProgressCallback | None = None,
                  seed_urls: list[str] | None = None) -> None:
        """Execute the full clone pipeline."""
        start_url = normalize_url(job.url)
        domain = job.domain

        # Create output directory
        timestamp = int(time.time())
        dir_name = f"{domain}_{timestamp}"
        output_path = os.path.join(self._config.output_dir, dir_name)
        os.makedirs(output_path, exist_ok=True)
        job.output_path = output_path

        # url_map: absolute_url -> local_path (relative to output_path)
        url_map: dict[str, str] = {}
        # Store downloaded content for rewriting later
        html_assets: dict[str, Asset] = {}  # url -> Asset (HTML pages)
        css_assets: dict[str, Asset] = {}   # url -> Asset (CSS files)
        all_assets: dict[str, Asset] = {}   # url -> Asset (all non-HTML assets)

        # Optional Playwright renderer — use ThreadedPlaywrightRenderer to avoid
        # Windows event loop issues (subprocess_exec NotImplementedError).
        # Auto-enable when auth cookies are present (JS-rendered nav links).
        use_renderer = self._config.use_playwright or bool(self._config.auth_cookies)
        renderer: ThreadedPlaywrightRenderer | PlaywrightRenderer | None = None
        if use_renderer and is_playwright_available():
            renderer = ThreadedPlaywrightRenderer(
                user_agent=self._config.user_agent,
                cookies=self._config.auth_cookies,
                target_url=start_url,
            )

        # robots.txt checker
        robots = RobotsChecker(self._config.user_agent)

        await self._downloader.start(target_url=start_url)
        if renderer:
            await renderer.start()
        try:
            # Load robots.txt if configured
            if self._config.respect_robots:
                await robots.load(start_url, self._downloader.fetch)
                # Apply crawl delay from robots.txt if larger than configured
                robot_delay = robots.crawl_delay(start_url)
                if robot_delay > self._downloader._rate_limiter._delay:
                    self._downloader._rate_limiter._delay = robot_delay

            # Discover URLs from sitemap if configured
            sitemap_urls: list[str] = []
            if self._config.use_sitemap:
                sitemap_urls = await robots.get_sitemap_urls(start_url, self._downloader.fetch)

            # Phase 1: BFS crawl HTML pages
            job.status = JobStatus.CRAWLING
            await self._notify(progress, {"type": "status", "status": "crawling"})

            visited: set[str] = set()
            queue: deque[tuple[str, int]] = deque()
            queue.append((start_url, 0))
            visited.add(start_url)

            # Add sitemap URLs to the queue
            for surl in sitemap_urls:
                norm = normalize_url(surl)
                if norm not in visited and is_same_domain(norm, domain):
                    visited.add(norm)
                    queue.append((norm, 1))

            # Add seed URLs discovered from authenticated browser session
            if seed_urls:
                for surl in seed_urls:
                    norm = normalize_url(surl)
                    if norm not in visited and is_same_domain(norm, domain):
                        visited.add(norm)
                        queue.append((norm, 1))
                logger.info("Injected %d seed URLs from login session", len(seed_urls))

            pending_assets: set[str] = set()

            while queue:
                # Cancellation check point 1: BFS loop
                if job.cancel_requested:
                    job.status = JobStatus.CANCELLED
                    await self._notify(progress, {"type": "status", "status": "cancelled"})
                    return

                url, depth = queue.popleft()
                if job.pages_crawled >= self._config.max_pages:
                    break

                # robots.txt check
                if self._config.respect_robots and not robots.can_fetch(url):
                    logger.info("Blocked by robots.txt: %s", url)
                    continue

                # Fetch page (optionally via Playwright)
                if renderer:
                    try:
                        html_text, intercepted = await renderer.render(url)
                        body = html_text.encode("utf-8")
                        status = 200
                        content_type = "text/html"
                        # Add intercepted asset URLs
                        for iurl in intercepted:
                            norm = normalize_url(iurl)
                            if norm not in pending_assets and norm not in url_map:
                                pending_assets.add(norm)
                    except Exception as e:
                        logger.warning("Playwright render FAILED for %s: %s, falling back to raw fetch", url, e)
                        status, body, content_type, _final, err = await self._downloader.fetch_with_final_url(url)
                        if err:
                            job.errors.append(err)
                            await self._notify(progress, {
                                "type": "error", "url": url,
                                "error": err.message, "category": err.category.value,
                            })
                            continue
                        if self._is_auth_redirect(url, _final):
                            logger.info("Skipping %s — redirected to login: %s", url, _final)
                            continue
                else:
                    status, body, content_type, final_url, err = await self._downloader.fetch_with_final_url(url)

                if not renderer:
                    if err:
                        job.errors.append(err)
                        await self._notify(progress, {
                            "type": "error", "url": url,
                            "error": err.message, "category": err.category.value,
                        })
                        continue
                    # Detect auth redirects: if the final URL is a login/auth page,
                    # skip this page — we got the login form, not the real content.
                    if self._is_auth_redirect(url, final_url):
                        logger.info("Skipping %s — redirected to login: %s", url, final_url)
                        continue

                if status == 0 or not body:
                    job.errors.append(ErrorDetail(
                        url=url, category=ErrorCategory.HTTP_ERROR,
                        message="Empty response", status_code=status,
                    ))
                    await self._notify(progress, {"type": "error", "url": url, "error": "fetch failed"})
                    continue

                local_path = url_to_local_path(url, domain)
                asset = Asset(
                    url=url, local_path=local_path,
                    asset_type=AssetType.HTML, content=body,
                    status_code=status, content_type=content_type,
                )
                html_assets[url] = asset
                url_map[url] = local_path

                job.pages_crawled += 1
                await self._notify(progress, {
                    "type": "page_crawled", "url": url,
                    "depth": depth, "pages_crawled": job.pages_crawled,
                })

                # Parse links and assets
                try:
                    html_text = decode_content(body, content_type)
                    page_links, asset_urls = parse_html(html_text, url, domain)
                except Exception as e:
                    logger.warning("Parse error for %s: %s", url, e)
                    job.errors.append(ErrorDetail(
                        url=url, category=ErrorCategory.PARSE_ERROR,
                        message=str(e),
                    ))
                    continue

                # Queue new page links
                if depth < self._config.max_depth:
                    for link in page_links:
                        if link not in visited:
                            visited.add(link)
                            queue.append((link, depth + 1))
                            job.pages_found += 1

                # Collect asset URLs
                for asset_url in asset_urls:
                    if asset_url not in pending_assets and asset_url not in url_map:
                        pending_assets.add(asset_url)

            job.assets_found = len(pending_assets)
            await self._notify(progress, {
                "type": "crawl_complete",
                "pages_crawled": job.pages_crawled,
                "assets_found": job.assets_found,
            })

            # Cancellation check point 2: before asset download
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                await self._notify(progress, {"type": "status", "status": "cancelled"})
                return

            # Phase 2: Download all assets (CSS first for priority, then rest)
            job.status = JobStatus.DOWNLOADING
            await self._notify(progress, {"type": "status", "status": "downloading"})

            # Split into CSS and non-CSS for priority ordering
            css_urls = set()
            other_urls = set()
            for asset_url in pending_assets:
                atype = classify_url(asset_url)
                if atype == AssetType.CSS:
                    css_urls.add(asset_url)
                else:
                    other_urls.add(asset_url)

            async def download_asset(asset_url: str) -> None:
                # Cancellation inside download
                if job.cancel_requested:
                    return

                status, body, content_type, err = await self._downloader.fetch(asset_url)
                if err:
                    job.errors.append(err)
                    return
                if status == 0 or not body:
                    job.errors.append(ErrorDetail(
                        url=asset_url, category=ErrorCategory.HTTP_ERROR,
                        message=f"Asset failed (status {status})", status_code=status,
                    ))
                    return

                asset_type = classify_url(asset_url, content_type)
                local_path = url_to_local_path(asset_url, domain)
                asset = Asset(
                    url=asset_url, local_path=local_path,
                    asset_type=asset_type, content=body,
                    status_code=status, content_type=content_type,
                )
                url_map[asset_url] = local_path
                all_assets[asset_url] = asset
                if asset_type == AssetType.CSS:
                    css_assets[asset_url] = asset

                job.assets_downloaded += 1
                await self._notify(progress, {
                    "type": "asset_downloaded",
                    "url": asset_url,
                    "asset_type": asset_type.value,
                    "assets_downloaded": job.assets_downloaded,
                    "assets_total": job.assets_found,
                })

            # Wave 1: CSS files first
            if css_urls:
                tasks = [download_asset(u) for u in css_urls]
                await asyncio.gather(*tasks, return_exceptions=True)

            # Parse CSS for secondary assets immediately after CSS download
            secondary_urls: set[str] = set()
            for css_url, asset in css_assets.items():
                try:
                    css_text = decode_content(asset.content, asset.content_type)
                    refs = parse_css(css_text, css_url)
                    for ref in refs:
                        if ref not in url_map and ref not in secondary_urls and ref not in other_urls:
                            secondary_urls.add(ref)
                except Exception as e:
                    logger.warning("CSS parse error for %s: %s", css_url, e)

            # Wave 2: Non-CSS + secondary assets together
            combined = other_urls | secondary_urls
            if secondary_urls:
                job.assets_found += len(secondary_urls)
                await self._notify(progress, {
                    "type": "secondary_assets_found",
                    "count": len(secondary_urls),
                    "assets_total": job.assets_found,
                })

            if combined:
                tasks = [download_asset(u) for u in combined]
                await asyncio.gather(*tasks, return_exceptions=True)

            # Cancellation check point 3: before rewrite
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                await self._notify(progress, {"type": "status", "status": "cancelled"})
                return

            # Phase 3: Rewrite URLs
            job.status = JobStatus.REWRITING
            await self._notify(progress, {"type": "status", "status": "rewriting"})

            # Rewrite HTML files
            for url, asset in html_assets.items():
                try:
                    html_text = decode_content(asset.content, asset.content_type)
                    rewritten = rewrite_html(html_text, url, url_map, asset.local_path)
                    asset.content = rewritten.encode("utf-8")
                except Exception as e:
                    logger.warning("HTML rewrite error for %s: %s", url, e)
                    job.errors.append(ErrorDetail(
                        url=url, category=ErrorCategory.PARSE_ERROR,
                        message=f"Rewrite error: {e}",
                    ))

            # Rewrite CSS files
            for url, asset in css_assets.items():
                try:
                    css_text = decode_content(asset.content, asset.content_type)
                    rewritten = rewrite_css(css_text, url, url_map, asset.local_path)
                    asset.content = rewritten.encode("utf-8")
                except Exception as e:
                    logger.warning("CSS rewrite error for %s: %s", url, e)
                    job.errors.append(ErrorDetail(
                        url=url, category=ErrorCategory.PARSE_ERROR,
                        message=f"CSS rewrite error: {e}",
                    ))

            # Phase 4: Write files to disk (async I/O)
            await self._notify(progress, {"type": "status", "status": "saving"})

            all_items = list(html_assets.values()) + list(all_assets.values())
            write_sem = asyncio.Semaphore(20)

            async def write_file(asset: Asset) -> None:
                async with write_sem:
                    try:
                        safe_local = asset.local_path.replace("/", os.sep)
                        file_path = os.path.join(output_path, safe_local)
                        if os.name == "nt":
                            file_path = "\\\\?\\" + os.path.abspath(file_path)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(asset.content)
                    except Exception as e:
                        logger.warning("Failed to write %s: %s", asset.local_path, e)
                        job.errors.append(ErrorDetail(
                            url=asset.url, category=ErrorCategory.UNKNOWN,
                            message=f"Write error: {e}",
                        ))

            await asyncio.gather(*[write_file(a) for a in all_items], return_exceptions=True)

            # Compute total site size
            total_size = sum(len(a.content) for a in all_items if a.content)
            job.site_size_bytes = total_size

            job.status = JobStatus.DONE
            job.completed_at = time.time()
            await self._notify(progress, {
                "type": "done",
                "pages_crawled": job.pages_crawled,
                "assets_downloaded": job.assets_downloaded,
                "errors": len(job.errors),
                "output_path": output_path,
                "site_size_bytes": total_size,
            })

        except Exception as e:
            logger.exception("Clone failed for %s", job.url)
            job.status = JobStatus.FAILED
            job.completed_at = time.time()
            job.error_message = str(e)
            await self._notify(progress, {"type": "error", "error": str(e)})
        finally:
            await self._downloader.close()
            if renderer:
                await renderer.close()

    @staticmethod
    def _is_auth_redirect(requested_url: str, final_url: str) -> bool:
        """Detect if a fetch was redirected to a login/auth page."""
        if not final_url or not requested_url:
            return False
        req_path = urlparse(requested_url).path.rstrip("/")
        final_parsed = urlparse(final_url)
        final_path = final_parsed.path.rstrip("/")
        # Same path — no redirect
        if req_path == final_path:
            return False
        # Check if redirected to a common login/auth URL pattern
        login_keywords = ("login", "signin", "sign-in", "sign_in", "auth", "sso",
                          "cas/login", "oauth", "account/login", "saml")
        final_lower = final_parsed.path.lower() + "?" + final_parsed.query.lower()
        return any(kw in final_lower for kw in login_keywords)

    async def _notify(self, callback: ProgressCallback | None, data: dict[str, Any]) -> None:
        if callback:
            try:
                await callback(data)
            except Exception:
                pass
