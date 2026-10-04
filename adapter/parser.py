"""HTML parsing, content extraction, and path-matching helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup
from bs4.element import Tag

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

# 选中正文容器后再移除的噪声元素（导航/侧栏/表单等）
_NOISE_TAGS = ("nav", "aside", "form")
_NOISE_ROLES = {"navigation", "search", "banner", "contentinfo"}


def make_md_converter() -> html2text.HTML2Text:
    """Create a fresh HTML2Text instance.

    每份文档必须使用新实例：html2text 会在 handle() 之间保留文档级状态
    （缩写注释、脚注定义等），同线程复用会把上一页内容泄漏到下一页。
    """
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    return converter


def _density_score(el: Tag) -> float:
    """文本密度打分：正文长、链接文本占比低的容器得分高。

    侧栏/导航容器通常链接文本占比极高，因此得分被大幅压低。
    """
    text_len = len(el.get_text(strip=True))
    link_len = sum(len(a.get_text(strip=True)) for a in el.find_all("a"))
    return float(text_len - 2 * link_len)


def _depth(el: Tag) -> int:
    return sum(1 for _ in el.parents)


def extract_main(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    """Best-effort main-content extraction (no external deps).

    不取“第一个匹配容器”，而是对全部候选做文本密度打分：
    容器存在并不代表其中只有正文（例如语义容器里嵌套侧栏导航）。
    候选得分明显低于整页时回退到整页，避免误选空壳容器。
    """
    candidates: list[Tag] = []
    seen: set[int] = set()
    for sel in _MAIN_CONTENT_SELECTORS:
        for el in soup.select(sel):
            if id(el) not in seen:
                seen.add(id(el))
                candidates.append(el)

    body = soup.body
    if body is not None and id(body) not in seen:
        candidates.append(body)

    if not candidates:
        return soup

    # body 只是兜底参照：容器捕获了整页大部分有效文本时优先用容器
    body_score = _density_score(body) if body is not None else 0.0

    containers = [el for el in candidates if el is not body]
    if not containers:
        return soup
    best = max(containers, key=lambda el: (_density_score(el), _depth(el)))

    # 最佳容器连整页大部分有效文本都没覆盖到（空壳/误匹配）→ 用整页
    if body is not None and _density_score(best) < 0.6 * body_score:
        return soup

    # 在选中的容器内移除导航类噪声
    for el in list(best.find_all(_NOISE_TAGS)):
        el.decompose()
    for el in list(best.find_all(attrs={"role": True})):
        if str(el.get("role", "")).strip().lower() in _NOISE_ROLES:
            el.decompose()
    return best


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
    return make_md_converter().handle(html)[:max_chars]
