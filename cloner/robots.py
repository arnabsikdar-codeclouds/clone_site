import logging
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class RobotsChecker:
    """Check robots.txt compliance and parse sitemaps."""

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._crawl_delays: dict[str, float] = {}

    async def load(self, base_url: str, fetch_fn) -> None:
        """Load robots.txt for the given base URL's domain.
        fetch_fn should be an async callable(url) -> (status, body, content_type, error)."""
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._parsers:
            return

        robots_url = urljoin(origin, "/robots.txt")
        try:
            status, body, _, _ = await fetch_fn(robots_url)
            if status == 200 and body:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                lines = body.decode("utf-8", errors="replace")
                parser.parse(lines.splitlines())
                self._parsers[origin] = parser

                # Extract crawl-delay
                delay = parser.crawl_delay(self._user_agent)
                if delay:
                    self._crawl_delays[origin] = float(delay)
            else:
                # No robots.txt — allow everything
                self._parsers[origin] = None
        except Exception as e:
            logger.warning("Failed to fetch robots.txt for %s: %s", origin, e)
            self._parsers[origin] = None

    def can_fetch(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(origin)
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float:
        """Get crawl delay for the URL's domain."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return self._crawl_delays.get(origin, 0.0)

    async def get_sitemap_urls(self, base_url: str, fetch_fn) -> list[str]:
        """Parse sitemap.xml and return discovered URLs."""
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # Check if robots.txt specified sitemaps
        sitemap_urls_to_check = [urljoin(origin, "/sitemap.xml")]
        parser = self._parsers.get(origin)
        if parser and hasattr(parser, "site_maps") and parser.site_maps():
            sitemap_urls_to_check = list(parser.site_maps())

        discovered: list[str] = []
        for sitemap_url in sitemap_urls_to_check:
            try:
                status, body, _, _ = await fetch_fn(sitemap_url)
                if status == 200 and body:
                    text = body.decode("utf-8", errors="replace")
                    discovered.extend(_parse_sitemap_xml(text))
            except Exception as e:
                logger.debug("Sitemap fetch failed %s: %s", sitemap_url, e)

        return discovered


def _parse_sitemap_xml(text: str) -> list[str]:
    """Simple XML parsing for sitemap — extract <loc> tags."""
    import re
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.IGNORECASE)
