from pydantic import BaseModel


class CloneRequest(BaseModel):
    url: str
    max_depth: int | None = None
    max_pages: int | None = None
    verify_ssl: bool | None = None
    request_delay: float | None = None
    respect_robots: bool | None = None
    use_sitemap: bool | None = None
    user_agent: str | None = None
    auth_cookies: dict[str, str] | None = None
    auth_headers: dict[str, str] | None = None
    use_playwright: bool | None = None
    seed_urls: list[str] | None = None


class ErrorDetailResponse(BaseModel):
    url: str
    category: str
    message: str
    status_code: int


class JobResponse(BaseModel):
    job_id: str
    url: str
    domain: str
    status: str
    pages_crawled: int
    assets_downloaded: int
    errors_count: int
    error_message: str
    errors: list[ErrorDetailResponse] = []
    site_size_bytes: int = 0
    created_at: float = 0.0
    completed_at: float = 0.0


class CloneResponse(BaseModel):
    job_id: str
    message: str
    warning: str = ""


class LoginRequest(BaseModel):
    url: str


class LoginStartResponse(BaseModel):
    session_id: str
    message: str


class LoginSessionResponse(BaseModel):
    session_id: str
    status: str
    cookies: dict[str, str] | None = None
    discovered_urls: list[str] = []
    error: str = ""
