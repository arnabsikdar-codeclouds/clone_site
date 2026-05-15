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
    CANCELLED = "cancelled"


class ErrorCategory(Enum):
    TIMEOUT = "timeout"
    DNS_FAILURE = "dns_failure"
    HTTP_ERROR = "http_error"
    SSL_ERROR = "ssl_error"
    TOO_LARGE = "too_large"
    PARSE_ERROR = "parse_error"
    UNKNOWN = "unknown"


@dataclass
class ErrorDetail:
    url: str
    category: ErrorCategory
    message: str
    status_code: int = 0


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
    errors: list[ErrorDetail] = field(default_factory=list)
    error_message: str = ""
    cancel_requested: bool = False
    created_at: float = 0.0
    completed_at: float = 0.0
    site_size_bytes: int = 0


# Type alias for progress callbacks
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
