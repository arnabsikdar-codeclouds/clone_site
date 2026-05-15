"""Tests for cloner.encoding module."""

import pytest
from cloner.encoding import decode_content


class TestDecodeContent:
    def test_utf8_default(self):
        body = "Hello World".encode("utf-8")
        result = decode_content(body)
        assert result == "Hello World"

    def test_charset_from_content_type(self):
        body = "Hello".encode("utf-8")
        result = decode_content(body, "text/html; charset=utf-8")
        assert result == "Hello"

    def test_latin1_from_content_type(self):
        body = "caf\xe9".encode("latin-1")
        result = decode_content(body, "text/html; charset=iso-8859-1")
        assert result == "caf\xe9"

    def test_charset_from_html_meta(self):
        body = b'<html><head><meta charset="utf-8"></head><body>Hello</body></html>'
        result = decode_content(body)
        assert "Hello" in result

    def test_charset_from_xml_declaration(self):
        body = b'<?xml version="1.0" encoding="utf-8"?><root>Hello</root>'
        result = decode_content(body)
        assert "Hello" in result

    def test_fallback_on_bad_encoding(self):
        body = b'\xff\xfe invalid utf-8'
        # Should not raise, falls back to replace
        result = decode_content(body, "text/html; charset=nonexistent")
        assert isinstance(result, str)

    def test_empty_body(self):
        result = decode_content(b"")
        assert result == ""
