import re


def decode_content(body: bytes, content_type: str = "") -> str:
    """Decode bytes to string using charset from Content-Type, HTML meta, or XML declaration."""
    charset = _charset_from_content_type(content_type)
    if charset:
        return _try_decode(body, charset)

    # Try HTML meta charset
    charset = _charset_from_html_meta(body)
    if charset:
        return _try_decode(body, charset)

    # Try XML declaration
    charset = _charset_from_xml(body)
    if charset:
        return _try_decode(body, charset)

    # Default to UTF-8
    return _try_decode(body, "utf-8")


_CT_CHARSET_RE = re.compile(r"charset=([^\s;]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(rb'<meta[^>]+charset=["\']?([^"\'\s;>]+)', re.IGNORECASE)
_META_HTTP_EQUIV_RE = re.compile(
    rb'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)', re.IGNORECASE
)
_XML_ENCODING_RE = re.compile(rb'<\?xml[^>]+encoding=["\']([^"\']+)', re.IGNORECASE)


def _charset_from_content_type(content_type: str) -> str | None:
    m = _CT_CHARSET_RE.search(content_type)
    return m.group(1).strip().lower() if m else None


def _charset_from_html_meta(body: bytes) -> str | None:
    # Only check first 4KB
    head = body[:4096]
    m = _META_CHARSET_RE.search(head)
    if m:
        return m.group(1).decode("ascii", errors="ignore").strip().lower()
    m = _META_HTTP_EQUIV_RE.search(head)
    if m:
        return m.group(1).decode("ascii", errors="ignore").strip().lower()
    return None


def _charset_from_xml(body: bytes) -> str | None:
    head = body[:256]
    m = _XML_ENCODING_RE.search(head)
    return m.group(1).decode("ascii", errors="ignore").strip().lower() if m else None


def _try_decode(body: bytes, charset: str) -> str:
    try:
        return body.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return body.decode("utf-8", errors="replace")
