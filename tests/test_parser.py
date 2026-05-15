"""Tests for cloner.parser module."""

import pytest
from cloner.parser import parse_html, parse_css


class TestParseHtml:
    def test_extract_links(self):
        html = '<html><body><a href="/about">About</a><a href="/contact">Contact</a></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/about" in links
        assert "https://example.com/contact" in links

    def test_extract_stylesheets(self):
        html = '<html><head><link rel="stylesheet" href="/css/style.css"></head><body></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/css/style.css" in assets

    def test_extract_scripts(self):
        html = '<html><body><script src="/js/app.js"></script></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/js/app.js" in assets

    def test_extract_images(self):
        html = '<html><body><img src="/img/logo.png"></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/img/logo.png" in assets

    def test_extract_srcset(self):
        html = '<html><body><img srcset="/img/small.jpg 300w, /img/large.jpg 600w"></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/img/small.jpg" in assets
        assert "https://example.com/img/large.jpg" in assets

    def test_skip_external_links(self):
        html = '<html><body><a href="https://other.com/page">External</a></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert len(links) == 0

    def test_skip_mailto_and_javascript(self):
        html = '<html><body><a href="mailto:test@example.com">Email</a><a href="javascript:void(0)">Click</a></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert len(links) == 0

    def test_base_tag_resolution(self):
        html = '<html><head><base href="https://example.com/sub/"></head><body><a href="page.html">Link</a></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/sub/page.html" in links

    def test_inline_style_urls(self):
        html = '<html><body><div style="background: url(/img/bg.png)"></div></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/img/bg.png" in assets

    def test_style_block_urls(self):
        html = '<html><head><style>body { background: url(/img/bg.png); }</style></head><body></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/img/bg.png" in assets

    def test_video_and_audio(self):
        html = '<html><body><video src="/video/clip.mp4" poster="/img/poster.jpg"></video></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/video/clip.mp4" in assets
        assert "https://example.com/img/poster.jpg" in assets

    def test_favicon(self):
        html = '<html><head><link rel="icon" href="/favicon.ico"></head><body></body></html>'
        links, assets = parse_html(html, "https://example.com/", "example.com")
        assert "https://example.com/favicon.ico" in assets


class TestParseCss:
    def test_url_references(self):
        css = 'body { background: url("/img/bg.png"); }'
        urls = parse_css(css, "https://example.com/css/style.css")
        assert "https://example.com/img/bg.png" in urls

    def test_font_face(self):
        css = '@font-face { src: url("../fonts/font.woff2"); }'
        urls = parse_css(css, "https://example.com/css/style.css")
        assert "https://example.com/fonts/font.woff2" in urls

    def test_import_url(self):
        css = '@import url("base.css");'
        urls = parse_css(css, "https://example.com/css/style.css")
        assert "https://example.com/css/base.css" in urls

    def test_import_string(self):
        css = '@import "base.css";'
        urls = parse_css(css, "https://example.com/css/style.css")
        assert "https://example.com/css/base.css" in urls

    def test_skip_data_urls(self):
        css = 'body { background: url("data:image/png;base64,abc"); }'
        urls = parse_css(css, "https://example.com/css/style.css")
        assert len(urls) == 0

    def test_multiple_urls(self):
        css = """
        .a { background: url("/img/a.png"); }
        .b { background: url("/img/b.png"); }
        """
        urls = parse_css(css, "https://example.com/css/style.css")
        assert len(urls) == 2
