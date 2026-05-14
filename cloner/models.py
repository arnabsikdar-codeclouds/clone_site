from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, Any


class AssetType(Enum):
    HTML = "html"
    CSS = "css"
    JS = "js"
    IMAGE = "image"
    FONT = "font"
    VIDEO = "video"
    OTHER = "other"


class JobStatus(Enum):
    PENDING = "pending"
    CRAWLING = "crawling"
    DOWNLOADING = "downloading"
    REWRITING = "rewriting"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Asset:
    url: str
    local_path: str
    asset_type: AssetType
    content: bytes | None = None
    status_code: int = 0
    content_type: str = ""
    error: str = ""


@dataclass
class CrawlResult:
    url: str
    depth: int
    links: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class CloneJob:
    job_id: str
    url: str
    domain: str
    status: JobStatus = JobStatus.PENDING
    output_path: str = ""
    pages_found: int = 0
    pages_crawled: int = 0
    assets_found: int = 0
    assets_downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    error_message: str = ""


# Type alias for progress callbacks
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
