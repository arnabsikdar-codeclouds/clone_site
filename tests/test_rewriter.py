"""Tests for cloner.rewriter module."""

import pytest
from cloner.rewriter import rewrite_html, rewrite_css


class TestRewriteHtml:
    def test_rewrite_link(self):
        html = '<html><body><a href="https://example.com/about">About</a></body></html>'
        url_map = {"https://example.com/about": "about/index.html"}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "about/index.html" in result

    def test_rewrite_stylesheet(self):
        html = '<html><head><link rel="stylesheet" href="https://example.com/css/style.css"></head><body></body></html>'
        url_map = {"https://example.com/css/style.css": "css/style.css"}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "css/style.css" in result

    def test_rewrite_script(self):
        html = '<html><body><script src="https://example.com/js/app.js"></script></body></html>'
        url_map = {"https://example.com/js/app.js": "js/app.js"}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "js/app.js" in result

    def test_rewrite_image(self):
        html = '<html><body><img src="https://example.com/img/logo.png"></body></html>'
        url_map = {"https://example.com/img/logo.png": "img/logo.png"}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "img/logo.png" in result

    def test_leave_external_urls(self):
        html = '<html><body><a href="https://other.com/page">External</a></body></html>'
        url_map = {}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "https://other.com/page" in result

    def test_leave_mailto(self):
        html = '<html><body><a href="mailto:test@example.com">Email</a></body></html>'
        url_map = {}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "mailto:test@example.com" in result

    def test_base_tag_removed(self):
        html = '<html><head><base href="https://example.com/"></head><body></body></html>'
        url_map = {}
        result = rewrite_html(html, "https://example.com/", url_map, "index.html")
        assert "<base" not in result

    def test_relative_path_from_subdir(self):
        html = '<html><body><img src="https://example.com/img/logo.png"></body></html>'
        url_map = {"https://example.com/img/logo.png": "img/logo.png"}
        result = rewrite_html(html, "https://example.com/sub/page.html", url_map, "sub/page.html")
        assert "../img/logo.png" in result


class TestRewriteCss:
    def test_rewrite_url(self):
        css = 'body { background: url("https://example.com/img/bg.png"); }'
        url_map = {"https://example.com/img/bg.png": "img/bg.png"}
        result = rewrite_css(css, "https://example.com/css/style.css", url_map, "css/style.css")
        assert "../img/bg.png" in result

    def test_leave_external_url(self):
        css = 'body { background: url("https://cdn.example.com/bg.png"); }'
        url_map = {}
        result = rewrite_css(css, "https://example.com/css/style.css", url_map, "css/style.css")
        assert "https://cdn.example.com/bg.png" in result

    def test_leave_data_url(self):
        css = 'body { background: url("data:image/png;base64,abc"); }'
        url_map = {}
        result = rewrite_css(css, "https://example.com/css/style.css", url_map, "css/style.css")
        assert "data:image/png;base64,abc" in result
