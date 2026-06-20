"""HTML parsing, content extraction, and path-matching helpers."""
from __future__ import annotations

import re
import threading
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup
from bs4.element import Tag

_h2t_local = threading.local()

_MAIN_CONTENT_SELECTORS = (
    "main",
    "article",
    '[role="main"]',
    ".post-content",
    ".article-content",
    ".content",
    "#content",
    "#main",
    ".markdown-body",
)


def get_md_converter() -> html2text.HTML2Text:
    """Return a thread-local HTML2Text instance (not thread-safe to share)."""
    converter = getattr(_h2t_local, "converter", None)
    if converter is None:
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        _h2t_local.converter = converter
    return converter


def extract_main(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    """Best-effort main-content extraction (no external deps)."""
    for sel in _MAIN_CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            return el
    return soup


def get_meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name}) or soup.find(
        "meta", attrs={"property": f"og:{name}"}
    )
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


def match_path(url: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    path = urlparse(url).path
    for pat in patterns:
        if pat.startswith("/") and path.startswith(pat):
            return True
        if "*" in pat and re.match(pat.replace("*", ".*"), path):
            return True
    return False


def html_to_markdown(html: str, max_chars: int) -> str:
    return get_md_converter().handle(html)[:max_chars]
