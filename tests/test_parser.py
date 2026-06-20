"""Tests for parser helpers (pure functions)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from adapter.parser import (
    extract_main,
    get_meta,
    html_to_markdown,
    match_path,
)


def test_match_path_no_patterns_matches_all():
    assert match_path("https://example.com/any/path", None) is True
    assert match_path("https://example.com/any/path", []) is True


def test_match_path_prefix_match():
    assert match_path("https://example.com/blog/post-1", ["/blog"]) is True
    assert match_path("https://example.com/about", ["/blog"]) is False


def test_match_path_wildcard():
    assert match_path("https://example.com/docs/2024/x", ["/docs/*"]) is True
    assert match_path("https://example.com/api/v1", ["/docs/*"]) is False


def test_get_meta_by_name():
    html = '<html><head><meta name="description" content="hello world"></head><body></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == "hello world"


def test_get_meta_by_og_property():
    html = '<html><head><meta property="og:description" content="og content"></head></html>'
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == "og content"


def test_get_meta_missing_returns_empty():
    html = "<html><head></head></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == ""


def test_extract_main_finds_article():
    html = """
    <html><body>
      <header>nav</header>
      <article><p>main content here</p></article>
      <footer>foot</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    main = extract_main(soup)
    assert main.name == "article"
    assert "main content here" in main.get_text()


def test_extract_main_falls_back_to_soup():
    html = "<html><body><p>no semantic tags</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert extract_main(soup) is soup


def test_html_to_markdown_truncates():
    html = "<p>" + ("a " * 1000) + "</p>"
    md = html_to_markdown(html, max_chars=50)
    assert len(md) <= 50


def test_html_to_markdown_basic():
    md = html_to_markdown("<h1>Title</h1><p>Body</p>", max_chars=1000)
    assert "Title" in md
    assert "Body" in md
