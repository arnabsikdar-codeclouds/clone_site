import hashlib
import os
import posixpath
from urllib.parse import urlparse, urlunparse, urljoin, unquote

from .models import AssetType

_EXTENSION_MAP: dict[str, AssetType] = {}
for _ext in (".html", ".htm", ".xhtml"):
    _EXTENSION_MAP[_ext] = AssetType.HTML
for _ext in (".css",):
    _EXTENSION_MAP[_ext] = AssetType.CSS
for _ext in (".js", ".mjs"):
    _EXTENSION_MAP[_ext] = AssetType.JS
for _ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif"):
    _EXTENSION_MAP[_ext] = AssetType.IMAGE
for _ext in (".woff", ".woff2", ".ttf", ".otf", ".eot"):
    _EXTENSION_MAP[_ext] = AssetType.FONT
for _ext in (".mp4", ".webm", ".ogg", ".ogv"):
    _EXTENSION_MAP[_ext] = AssetType.VIDEO


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Normalize a URL: resolve relative, strip fragment, lowercase scheme+host."""
    if base_url:
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port = None
    netloc = host
    if port:
        netloc = f"{host}:{port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def is_same_domain(url: str, domain: str) -> bool:
    """Check if URL belongs to the target domain (including subdomains)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    domain = domain.lower()
    return host == domain or host.endswith(f".{domain}")


def url_to_local_path(url: str, domain: str) -> str:
    """Convert an absolute URL to a local filesystem path relative to output dir."""
    parsed = urlparse(url)
    path = unquote(parsed.path)

    # Remove leading slash
    path = path.lstrip("/")

    # If path is empty or ends with /, add index.html
    if not path or path.endswith("/"):
        path = path + "index.html"

    # If the last component has no extension, treat as directory
    _, ext = posixpath.splitext(posixpath.basename(path))
    if not ext:
        path = path + "/index.html"

    # Append query string to filename to differentiate
    if parsed.query:
        dir_part = posixpath.dirname(path)
        base = posixpath.basename(path)
        name, ext = posixpath.splitext(base)
        safe_query = parsed.query.replace("&", "_").replace("=", "-")
        base = f"{name}_{safe_query}{ext}"
        path = posixpath.join(dir_part, base) if dir_part else base

    # Sanitize path components
    parts = path.replace("\\", "/").split("/")
    sanitized = []
    for part in parts:
        # Remove dangerous characters
        part = part.replace("..", "_").replace(":", "_")
        if part and part != ".":
            # Truncate individual filename components that are too long (Windows 255 limit)
            if len(part) > 200:
                name, ext = posixpath.splitext(part)
                short_hash = hashlib.md5(name.encode()).hexdigest()[:12]
                part = name[:80] + "_" + short_hash + ext
            sanitized.append(part)

    result = "/".join(sanitized) if sanitized else "index.html"

    # Also guard total path length (Windows 260 char limit minus output dir overhead)
    if len(result) > 200:
        ext = posixpath.splitext(result)[1]
        path_hash = hashlib.md5(result.encode()).hexdigest()[:16]
        # Keep first directory component + hashed name
        first_dir = sanitized[0] if sanitized else ""
        result = f"{first_dir}/{path_hash}{ext}" if first_dir else f"{path_hash}{ext}"

    return result


def make_relative_path(from_file: str, to_file: str) -> str:
    """Compute relative path from one local file to another."""
    from_dir = posixpath.dirname(from_file)
    rel = posixpath.relpath(to_file, from_dir)
    # Ensure forward slashes
    rel = rel.replace("\\", "/")
    return rel


def classify_url(url: str, content_type: str = "") -> AssetType:
    """Guess asset type from URL extension or content-type header."""
    parsed = urlparse(url)
    _, ext = posixpath.splitext(parsed.path.lower())
    if ext in _EXTENSION_MAP:
        return _EXTENSION_MAP[ext]

    # Fall back to content-type
    ct = content_type.lower().split(";")[0].strip()
    if "html" in ct:
        return AssetType.HTML
    if "css" in ct:
        return AssetType.CSS
    if "javascript" in ct or "ecmascript" in ct:
        return AssetType.JS
    if ct.startswith("image/"):
        return AssetType.IMAGE
    if "font" in ct:
        return AssetType.FONT
    if ct.startswith("video/"):
        return AssetType.VIDEO

    return AssetType.OTHER
