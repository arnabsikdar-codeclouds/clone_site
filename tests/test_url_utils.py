"""Tests for cloner.url_utils module."""

import pytest
from cloner.url_utils import (
    normalize_url, is_same_domain, url_to_local_path,
    make_relative_path, classify_url,
)
from cloner.models import AssetType


class TestNormalizeUrl:
    def test_basic_normalization(self):
        assert normalize_url("https://Example.COM/path") == "https://example.com/path"

    def test_strip_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_resolve_relative(self):
        assert normalize_url("/about", "https://example.com/") == "https://example.com/about"

    def test_resolve_relative_deep(self):
        result = normalize_url("../img/logo.png", "https://example.com/css/style.css")
        assert result == "https://example.com/img/logo.png"

    def test_default_port_stripped(self):
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_non_default_port_kept(self):
        assert normalize_url("https://example.com:8080/path") == "https://example.com:8080/path"

    def test_empty_path_gets_slash(self):
        result = normalize_url("https://example.com")
        assert result == "https://example.com/"

    def test_query_preserved(self):
        result = normalize_url("https://example.com/page?q=test&lang=en")
        assert "q=test" in result
        assert "lang=en" in result

    def test_non_http_unchanged(self):
        assert normalize_url("mailto:test@example.com") == "mailto:test@example.com"
        assert normalize_url("javascript:void(0)") == "javascript:void(0)"


class TestIsSameDomain:
    def test_exact_match(self):
        assert is_same_domain("https://example.com/page", "example.com") is True

    def test_subdomain_match(self):
        assert is_same_domain("https://www.example.com/page", "example.com") is True
        assert is_same_domain("https://blog.example.com/page", "example.com") is True

    def test_different_domain(self):
        assert is_same_domain("https://other.com/page", "example.com") is False

    def test_partial_name_no_match(self):
        assert is_same_domain("https://notexample.com/page", "example.com") is False


class TestUrlToLocalPath:
    def test_basic_page(self):
        result = url_to_local_path("https://example.com/about", "example.com")
        assert result == "about/index.html"

    def test_root_url(self):
        result = url_to_local_path("https://example.com/", "example.com")
        assert result == "index.html"

    def test_with_extension(self):
        result = url_to_local_path("https://example.com/style.css", "example.com")
        assert result == "style.css"

    def test_nested_path(self):
        result = url_to_local_path("https://example.com/a/b/page.html", "example.com")
        assert result == "a/b/page.html"

    def test_path_traversal_sanitized(self):
        result = url_to_local_path("https://example.com/../../etc/passwd", "example.com")
        assert ".." not in result

    def test_query_in_filename(self):
        result = url_to_local_path("https://example.com/page?id=1&lang=en", "example.com")
        assert "id-1" in result or "id" in result

    def test_long_path_truncated(self):
        long_path = "a" * 300
        result = url_to_local_path(f"https://example.com/{long_path}.html", "example.com")
        assert len(result) <= 250


class TestMakeRelativePath:
    def test_same_directory(self):
        result = make_relative_path("css/style.css", "css/font.woff")
        assert result == "font.woff"

    def test_parent_directory(self):
        result = make_relative_path("css/style.css", "images/logo.png")
        assert result == "../images/logo.png"

    def test_root_to_nested(self):
        result = make_relative_path("index.html", "css/style.css")
        assert result == "css/style.css"


class TestClassifyUrl:
    def test_html_extension(self):
        assert classify_url("https://example.com/page.html") == AssetType.HTML

    def test_css_extension(self):
        assert classify_url("https://example.com/style.css") == AssetType.CSS

    def test_js_extension(self):
        assert classify_url("https://example.com/app.js") == AssetType.JS

    def test_image_extensions(self):
        assert classify_url("https://example.com/logo.png") == AssetType.IMAGE
        assert classify_url("https://example.com/photo.jpg") == AssetType.IMAGE
        assert classify_url("https://example.com/icon.svg") == AssetType.IMAGE

    def test_font_extensions(self):
        assert classify_url("https://example.com/font.woff2") == AssetType.FONT

    def test_content_type_fallback(self):
        assert classify_url("https://example.com/file", "text/css; charset=utf-8") == AssetType.CSS
        assert classify_url("https://example.com/file", "text/html") == AssetType.HTML
        assert classify_url("https://example.com/file", "image/png") == AssetType.IMAGE

    def test_unknown(self):
        assert classify_url("https://example.com/file") == AssetType.OTHER
