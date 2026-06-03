import re
import logging

from bs4 import BeautifulSoup

from .url_utils import normalize_url, make_relative_path
from .parser import CSS_URL_RE

logger = logging.getLogger(__name__)


def rewrite_html(html: str, page_url: str, url_map: dict[str, str], page_local_path: str) -> str:
    """Rewrite URLs in HTML to relative local paths."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Handle <base> tag — remove it since we use relative paths
    base_url = page_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = normalize_url(base_tag["href"], page_url)
        base_tag.decompose()

    # Rewrite <a href>
    for tag in soup.find_all("a", href=True):
        tag["href"] = _rewrite_attr(tag["href"], base_url, url_map, page_local_path)

    # Rewrite <link href>
    for tag in soup.find_all("link", href=True):
        tag["href"] = _rewrite_attr(tag["href"], base_url, url_map, page_local_path)

    # Rewrite <script src>
    for tag in soup.find_all("script", src=True):
        tag["src"] = _rewrite_attr(tag["src"], base_url, url_map, page_local_path)

    # Rewrite <img src> and srcset
    for tag in soup.find_all("img"):
        if tag.get("src"):
            tag["src"] = _rewrite_attr(tag["src"], base_url, url_map, page_local_path)
        if tag.get("srcset"):
            tag["srcset"] = _rewrite_srcset(tag["srcset"], base_url, url_map, page_local_path)

    # Rewrite <source src/srcset>
    for tag in soup.find_all("source"):
        if tag.get("src"):
            tag["src"] = _rewrite_attr(tag["src"], base_url, url_map, page_local_path)
        if tag.get("srcset"):
            tag["srcset"] = _rewrite_srcset(tag["srcset"], base_url, url_map, page_local_path)

    # Rewrite <video>/<audio> src and poster
    for tag in soup.find_all(["video", "audio"]):
        if tag.get("src"):
            tag["src"] = _rewrite_attr(tag["src"], base_url, url_map, page_local_path)
        if tag.get("poster"):
            tag["poster"] = _rewrite_attr(tag["poster"], base_url, url_map, page_local_path)

    # Rewrite inline style url()
    for tag in soup.find_all(style=True):
        tag["style"] = _rewrite_css_text(tag["style"], base_url, url_map, page_local_path)

    # Rewrite <style> blocks
    for tag in soup.find_all("style"):
        if tag.string:
            tag.string = _rewrite_css_text(tag.string, base_url, url_map, page_local_path)

    # Rewrite <meta content> for og:image etc
    for tag in soup.find_all("meta", attrs={"content": True}):
        prop = tag.get("property", "") or tag.get("name", "")
        if "image" in prop.lower():
            content = tag["content"].strip()
            if content.startswith(("http://", "https://", "/")):
                tag["content"] = _rewrite_attr(content, base_url, url_map, page_local_path)

    return str(soup)


def rewrite_css(css_text: str, css_url: str, url_map: dict[str, str], css_local_path: str) -> str:
    """Rewrite url() references in CSS to relative local paths."""
    return _rewrite_css_text(css_text, css_url, url_map, css_local_path)


def _rewrite_attr(value: str, base_url: str, url_map: dict[str, str], from_path: str) -> str:
    """Rewrite a single URL attribute value."""
    value = value.strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return value
    abs_url = normalize_url(value, base_url)
    if abs_url in url_map:
        return make_relative_path(from_path, url_map[abs_url])
    return value


def _rewrite_srcset(srcset: str, base_url: str, url_map: dict[str, str], from_path: str) -> str:
    """Rewrite srcset attribute."""
    entries = []
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if parts:
            parts[0] = _rewrite_attr(parts[0], base_url, url_map, from_path)
            entries.append(" ".join(parts))
    return ", ".join(entries)


def _rewrite_css_text(css_text: str, base_url: str, url_map: dict[str, str], from_path: str) -> str:
    """Rewrite all url() values in CSS text."""
    def replacer(match: re.Match) -> str:
        quote = match.group(1)
        raw_url = match.group(2).strip()
        if not raw_url or raw_url.startswith("data:"):
            return match.group(0)
        abs_url = normalize_url(raw_url, base_url)
        if abs_url in url_map:
            new_url = make_relative_path(from_path, url_map[abs_url])
            return f"url({quote}{new_url}{quote})"
        return match.group(0)

    return CSS_URL_RE.sub(replacer, css_text)
