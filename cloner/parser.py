import re
import logging

from bs4 import BeautifulSoup

from .url_utils import normalize_url, is_same_domain, classify_url
from .models import AssetType

logger = logging.getLogger(__name__)

# Regex to find url(...) in CSS
CSS_URL_RE = re.compile(
    r"""url\(\s*(['"]?)(.*?)\1\s*\)""",
    re.IGNORECASE,
)

# Regex for @import "..." or @import url(...)
CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*(['"]?)(.*?)\1\s*\)|(['"])(.*?)\3)""",
    re.IGNORECASE,
)


def parse_html(html: str, page_url: str, domain: str) -> tuple[list[str], list[str]]:
    """Parse HTML and extract internal page links and asset URLs.
    Returns (page_links, asset_urls)."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Handle <base> tag
    base_url = page_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = normalize_url(base_tag["href"], page_url)

    page_links: list[str] = []
    asset_urls: list[str] = []

    # <a href>
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = normalize_url(href, base_url)
        if is_same_domain(abs_url, domain):
            asset_type = classify_url(abs_url)
            if asset_type == AssetType.HTML or asset_type == AssetType.OTHER:
                page_links.append(abs_url)
            else:
                asset_urls.append(abs_url)

    # <link href> (stylesheets, icons, etc.)
    for tag in soup.find_all("link", href=True):
        href = tag["href"].strip()
        if not href:
            continue
        abs_url = normalize_url(href, base_url)
        rel = " ".join(tag.get("rel", [])).lower()
        if "stylesheet" in rel:
            asset_urls.append(abs_url)
        elif "icon" in rel or "apple-touch-icon" in rel:
            asset_urls.append(abs_url)
        elif is_same_domain(abs_url, domain):
            asset_urls.append(abs_url)

    # <script src>
    for tag in soup.find_all("script", src=True):
        src = tag["src"].strip()
        if src:
            asset_urls.append(normalize_url(src, base_url))

    # <img src> and srcset
    for tag in soup.find_all("img"):
        if tag.get("src"):
            asset_urls.append(normalize_url(tag["src"].strip(), base_url))
        if tag.get("srcset"):
            asset_urls.extend(_parse_srcset(tag["srcset"], base_url))

    # <source src/srcset>
    for tag in soup.find_all("source"):
        if tag.get("src"):
            asset_urls.append(normalize_url(tag["src"].strip(), base_url))
        if tag.get("srcset"):
            asset_urls.extend(_parse_srcset(tag["srcset"], base_url))

    # <video src>, <audio src>
    for tag in soup.find_all(["video", "audio"], src=True):
        asset_urls.append(normalize_url(tag["src"].strip(), base_url))

    # <video poster>
    for tag in soup.find_all("video", poster=True):
        asset_urls.append(normalize_url(tag["poster"].strip(), base_url))

    # Inline style url() references
    for tag in soup.find_all(style=True):
        urls = _extract_css_urls(tag["style"], base_url)
        asset_urls.extend(urls)

    # <style> blocks
    for tag in soup.find_all("style"):
        if tag.string:
            urls = _extract_css_urls(tag.string, base_url)
            asset_urls.extend(urls)

    # <meta property="og:image"> and similar
    for tag in soup.find_all("meta", attrs={"content": True}):
        prop = tag.get("property", "") or tag.get("name", "")
        if "image" in prop.lower():
            content = tag["content"].strip()
            if content.startswith(("http://", "https://", "/")):
                asset_urls.append(normalize_url(content, base_url))

    return page_links, asset_urls


def parse_css(css_text: str, css_url: str) -> list[str]:
    """Extract all url() references from CSS text."""
    return _extract_css_urls(css_text, css_url)


def _extract_css_urls(css_text: str, base_url: str) -> list[str]:
    """Extract URLs from CSS url() and @import statements."""
    urls: list[str] = []
    for match in CSS_URL_RE.finditer(css_text):
        raw = match.group(2).strip()
        if raw and not raw.startswith("data:"):
            urls.append(normalize_url(raw, base_url))
    for match in CSS_IMPORT_RE.finditer(css_text):
        raw = match.group(2) or match.group(4)
        if raw and raw.strip() and not raw.strip().startswith("data:"):
            urls.append(normalize_url(raw.strip(), base_url))
    return urls


def _parse_srcset(srcset: str, base_url: str) -> list[str]:
    """Parse srcset attribute and return list of absolute URLs."""
    urls: list[str] = []
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if parts:
            urls.append(normalize_url(parts[0], base_url))
    return urls
