import asyncio
import logging
import os
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

from config import CloneConfig
from .models import CloneJob, Asset, AssetType, JobStatus, ProgressCallback
from .url_utils import normalize_url, is_same_domain, url_to_local_path, classify_url
from .downloader import Downloader
from .parser import parse_html, parse_css
from .rewriter import rewrite_html, rewrite_css

logger = logging.getLogger(__name__)


class CloneEngine:
    def __init__(self, config: CloneConfig) -> None:
        self._config = config
        self._downloader = Downloader(config)

    async def run(self, job: CloneJob, progress: ProgressCallback | None = None) -> None:
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

        await self._downloader.start()
        try:
            # Phase 1: BFS crawl HTML pages
            job.status = JobStatus.CRAWLING
            await self._notify(progress, {"type": "status", "status": "crawling"})

            visited: set[str] = set()
            queue: deque[tuple[str, int]] = deque()
            queue.append((start_url, 0))
            visited.add(start_url)
            pending_assets: set[str] = set()

            while queue:
                url, depth = queue.popleft()
                if job.pages_crawled >= self._config.max_pages:
                    break

                status, body, content_type = await self._downloader.fetch(url)
                if status == 0 or not body:
                    job.errors.append(f"Failed to fetch {url}")
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
                    html_text = body.decode("utf-8", errors="replace")
                    page_links, asset_urls = parse_html(html_text, url, domain)
                except Exception as e:
                    logger.warning("Parse error for %s: %s", url, e)
                    job.errors.append(f"Parse error: {url}: {e}")
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

            # Phase 2: Download all assets
            job.status = JobStatus.DOWNLOADING
            await self._notify(progress, {"type": "status", "status": "downloading"})

            async def download_asset(asset_url: str) -> None:
                status, body, content_type = await self._downloader.fetch(asset_url)
                if status == 0 or not body:
                    job.errors.append(f"Asset failed: {asset_url}")
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

            # Download in batches
            tasks = [download_asset(url) for url in pending_assets]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Phase 2.5: Parse CSS for secondary assets (fonts, bg images)
            secondary_urls: set[str] = set()
            for css_url, asset in css_assets.items():
                try:
                    css_text = asset.content.decode("utf-8", errors="replace")
                    refs = parse_css(css_text, css_url)
                    for ref in refs:
                        if ref not in url_map and ref not in secondary_urls:
                            secondary_urls.add(ref)
                except Exception as e:
                    logger.warning("CSS parse error for %s: %s", css_url, e)

            if secondary_urls:
                job.assets_found += len(secondary_urls)
                await self._notify(progress, {
                    "type": "secondary_assets_found",
                    "count": len(secondary_urls),
                    "assets_total": job.assets_found,
                })
                tasks = [download_asset(url) for url in secondary_urls]
                await asyncio.gather(*tasks, return_exceptions=True)

            # Phase 3: Rewrite URLs
            job.status = JobStatus.REWRITING
            await self._notify(progress, {"type": "status", "status": "rewriting"})

            # Rewrite HTML files
            for url, asset in html_assets.items():
                try:
                    html_text = asset.content.decode("utf-8", errors="replace")
                    rewritten = rewrite_html(html_text, url, url_map, asset.local_path)
                    asset.content = rewritten.encode("utf-8")
                except Exception as e:
                    logger.warning("HTML rewrite error for %s: %s", url, e)
                    job.errors.append(f"Rewrite error: {url}: {e}")

            # Rewrite CSS files
            for url, asset in css_assets.items():
                try:
                    css_text = asset.content.decode("utf-8", errors="replace")
                    rewritten = rewrite_css(css_text, url, url_map, asset.local_path)
                    asset.content = rewritten.encode("utf-8")
                except Exception as e:
                    logger.warning("CSS rewrite error for %s: %s", url, e)
                    job.errors.append(f"CSS rewrite error: {url}: {e}")

            # Phase 4: Write files to disk
            await self._notify(progress, {"type": "status", "status": "saving"})

            all_items = list(html_assets.values()) + list(all_assets.values())
            for asset in all_items:
                try:
                    # Convert forward slashes to OS separator for Windows compat
                    safe_local = asset.local_path.replace("/", os.sep)
                    file_path = os.path.join(output_path, safe_local)
                    # Use \\?\ prefix on Windows to support long paths
                    if os.name == "nt":
                        file_path = "\\\\?\\" + os.path.abspath(file_path)
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "wb") as f:
                        f.write(asset.content)
                except Exception as e:
                    logger.warning("Failed to write %s: %s", asset.local_path, e)
                    job.errors.append(f"Write error: {asset.local_path}: {e}")

            job.status = JobStatus.DONE
            await self._notify(progress, {
                "type": "done",
                "pages_crawled": job.pages_crawled,
                "assets_downloaded": job.assets_downloaded,
                "errors": len(job.errors),
                "output_path": output_path,
            })

        except Exception as e:
            logger.exception("Clone failed for %s", job.url)
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            await self._notify(progress, {"type": "error", "error": str(e)})
        finally:
            await self._downloader.close()

    async def _notify(self, callback: ProgressCallback | None, data: dict[str, Any]) -> None:
        if callback:
            try:
                await callback(data)
            except Exception:
                pass
