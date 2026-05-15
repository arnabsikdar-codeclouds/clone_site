from dataclasses import dataclass, field


@dataclass
class CloneConfig:
    max_depth: int = 10
    max_pages: int = 500
    concurrency: int = 10
    timeout: int = 30
    max_file_size: int = 50 * 1024 * 1024  # 50 MB
    user_agent: str = "StaticSiteCloner/1.0"
    output_dir: str = "output"

    # Retry logic (A3)
    max_retries: int = 3
    retry_base_delay: float = 1.0

    # SSL verification (B1)
    verify_ssl: bool = True

    # Rate limiting / politeness (B2)
    request_delay: float = 0.0

    # robots.txt (B3)
    respect_robots: bool = True
    use_sitemap: bool = False

    # Authentication (C4)
    auth_cookies: dict[str, str] = field(default_factory=dict)
    auth_headers: dict[str, str] = field(default_factory=dict)

    # Job cleanup TTL (D1) — seconds
    job_ttl: int = 3600

    # API rate limiting (D3)
    api_rate_limit: int = 10
    api_rate_window: int = 60

    # SPA rendering (E5)
    use_playwright: bool = False
