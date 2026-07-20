"""HTML parsing, content extraction, and path-matching helpers."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
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
    if isinstance(tag, Tag) and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


@dataclass(frozen=True)
class CompiledPathPattern:
    source: str
    regex: re.Pattern[str] | None


def compile_path_patterns(patterns: tuple[str, ...]) -> tuple[CompiledPathPattern, ...]:
    """Compile literal path globs; only ``*`` has wildcard meaning."""
    compiled = []
    for pattern in patterns:
        regex = None
        if "*" in pattern:
            source = re.escape(pattern).replace(r"\*", ".*")
            regex = re.compile(source)
        compiled.append(CompiledPathPattern(source=pattern, regex=regex))
    return tuple(compiled)


def match_path(url: str, patterns: tuple[CompiledPathPattern, ...] | None) -> bool:
    if not patterns:
        return True
    path = urlparse(url).path
    return any(
        pattern.regex.match(path) is not None
        if pattern.regex is not None
        else path.startswith(pattern.source)
        for pattern in patterns
    )


def html_to_markdown(html: str, max_chars: int) -> str:
    return get_md_converter().handle(html)[:max_chars]
