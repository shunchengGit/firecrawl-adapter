"""URL fetching: requests first, agent-browser headless fallback."""
from __future__ import annotations

import contextlib
import json
import logging
import math
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import config
from .parser import extract_main, get_meta, html_to_markdown

_log = logging.getLogger("adapter")

_ANTI_BOT_KEYWORDS = ("_waf_", "captcha", "验证码", "请求存在异常", "限制本次访问")

_SEARXNG_PAGE_SIZE = 20  # SearXNG default results per page

_DDG_LITE = "https://lite.duckduckgo.com/lite/"


def compile_search_query(
    base_query: str,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Build a query string with site: / -site: operators baked in.

    Inspired by firecrawl's search-query-builder.ts — puts domain filters
    directly into the search query so the upstream engine filters natively,
    avoiding post-filter result loss.
    """
    parts = [base_query]

    if include_domains:
        sites = " OR ".join(f"site:{d}" for d in include_domains)
        parts.append(f"({sites})")

    if exclude_domains:
        parts.extend(f"-site:{d}" for d in exclude_domains)

    return " ".join(parts)


def ddg_search(query: str, limit: int = 10) -> list[dict]:
    """Search DuckDuckGo (Lite) as a fallback when SearXNG returns empty.

    Uses the text-only lite.duckduckgo.com — no JS required.
    Returns empty list on any error (graceful degradation).
    """
    if limit <= 0:
        return []

    results: list[dict] = []
    try:
        params = urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(
            f"{_DDG_LITE}?{params}",
            headers={"User-Agent": config.user_agent},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read()

        soup = BeautifulSoup(html, "html.parser")
        # DDG Lite structure: table with tr rows, each has a link + snippet
        for row in soup.select("tr[class]")[:limit]:
            link = row.select_one("a[class='result-link']")
            snippet = row.select_one("td[class='result-snippet']")
            if link and link.get("href"):
                url_raw: str = link["href"]  # type: ignore[assignment]
                # DDG Lite wraps URLs in a redirect; extract the real URL from ///
                parsed = urlparse(url_raw)
                real_url = parsed.path.lstrip("/") if parsed.path.startswith("/l") else url_raw
                if "uddg=" in url_raw:
                    from urllib.parse import parse_qs
                    try:
                        real_url = parse_qs(parsed.query).get("uddg", [url_raw])[0]
                    except Exception:
                        real_url = url_raw

                results.append({
                    "title": link.get_text(strip=True) or query,
                    "url": real_url,
                    "content": snippet.get_text(separator=" ", strip=True) if snippet else "",
                })

        _log.info("DDG returned %d results for %r", len(results), query[:60])
    except Exception as e:
        _log.warning("DDG search failed (%s), returning empty", e)

    return results[:limit]


def find_agent_browser() -> str | None:
    """Locate the agent-browser CLI binary."""
    return shutil.which("agent-browser")


def scrape_url_headless(url: str, timeout: int = 30) -> tuple[str, str]:
    """agent-browser fallback for anti-bot-blocked pages.

    Returns (final_url, html).
    Raises Exception on failure — caller should catch and handle.
    """
    agent_bin = find_agent_browser()
    if not agent_bin:
        raise RuntimeError("agent-browser not found in PATH")

    nav_timeout = max(30, timeout + 10)
    session = f"adapter_{uuid.uuid4().hex[:8]}"

    try:
        result = subprocess.run(
            [agent_bin, "--session", session, "open", url],
            capture_output=True,
            text=True,
            timeout=nav_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"agent-browser open exit {result.returncode}: {result.stderr[:500]}"
            )

        final_url = url
        try:
            result = subprocess.run(
                [agent_bin, "--session", session, "get", "url", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    final_url = data.get("data", {}).get("url", url) or url
        except Exception:
            pass

        result = subprocess.run(
            [agent_bin, "--session", session, "eval", "document.documentElement.outerHTML"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"agent-browser eval exit {result.returncode}: {result.stderr[:500]}"
            )

        html: str = result.stdout.strip()
        try:
            parsed = json.loads(html)
            if isinstance(parsed, str):
                html = parsed
            elif isinstance(parsed, dict):
                value = parsed.get("result", parsed.get("value", html))
                if isinstance(value, str):
                    html = value
        except (json.JSONDecodeError, TypeError):
            pass

        return final_url, html
    finally:
        # 每次抓取后 close 自己的 session，确保 cookie 落盘。
        # 不关其他 daemon（Hermes 等可能在同时用）。
        with contextlib.suppress(Exception):
            subprocess.run(
                [agent_bin, "--session", session, "close"],
                capture_output=True,
                text=True,
                timeout=10,
            )


def searxng_search(
    query: str,
    limit: int = 5,
    engines: str | None = None,
    categories: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Search via SearXNG with pagination support.

    Fetches multiple pages if *limit* exceeds SearXNG's per-page count (20).
    Accepts optional engines / categories / language to override defaults.
    Returns empty list on any error (matches upstream firecrawl behavior).
    """
    if limit <= 0:
        return []

    engines = engines or config.searxng_engines or None
    categories = categories or config.searxng_categories

    pages_needed = max(1, math.ceil(limit / _SEARXNG_PAGE_SIZE))
    all_results: list[dict] = []

    for page in range(1, pages_needed + 1):
        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "pageno": str(page),
        }
        if categories:
            params["categories"] = categories
        if engines:
            params["engines"] = engines
        if language:
            params["language"] = language

        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{config.searxng_base}/search?{qs}",
            headers={"User-Agent": config.user_agent},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            _log.warning("SearXNG search failed for page %d (query=%r)", page, query[:80])
            break

        page_results = data.get("results", [])
        if not page_results:
            break

        for item in page_results:
            all_results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                }
            )

        if len(all_results) >= limit:
            break

    return all_results[:limit]


def check_searxng() -> bool:
    """Quick liveness probe for SearXNG. Returns True if reachable."""
    try:
        req = urllib.request.Request(
            config.searxng_base,
            headers={"User-Agent": config.user_agent},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except Exception:
        return False


def _is_likely_blocked(html_raw: str) -> bool:
    soup = BeautifulSoup(html_raw, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    body_text = soup.get_text(separator=" ", strip=True)
    if len(body_text) < 500:
        return True
    lower = html_raw.lower()
    return any(kw in lower for kw in _ANTI_BOT_KEYWORDS)


def scrape_url(
    url: str,
    formats: list[str] | None = None,
    only_main: bool = False,
    timeout: int = 15,
) -> dict:
    """Fetch a URL → Document dict with markdown / html / metadata.

    Uses requests.get first; falls back to agent-browser on failure.
    """
    final_url = url
    html_raw = ""
    used_headless = False

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": config.user_agent},
            timeout=min(timeout, 10),
            allow_redirects=True,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        final_url = resp.url
        html_raw = resp.text
        if _is_likely_blocked(html_raw):
            raise ValueError("body too short or anti-bot page — likely bot-blocked")
    except Exception as e:
        _log.warning("requests.get failed for %s (%s), trying agent-browser", url, e)
        html_raw = ""

    if not html_raw:
        try:
            final_url, html_raw = scrape_url_headless(url, timeout=timeout)
            used_headless = True
        except Exception as e:
            _log.warning("agent-browser also failed for %s: %s", url, e)
            return {
                "metadata": {"title": url, "url": url, "sourceURL": url},
                "links": [],
                "markdown": f"[fetch failed: {e}]",
            }

    soup = BeautifulSoup(html_raw, "html.parser")
    for t in soup(["script", "style", "footer", "header", "noscript"]):
        t.decompose()

    work_soup = extract_main(soup) if only_main else soup
    markdown = html_to_markdown(str(work_soup), config.max_scrape)

    title = (soup.title.string or "").strip() if soup.title else ""
    title = title or url

    metadata: dict = {
        "title": title,
        "url": url,
        "sourceURL": final_url,
        "description": get_meta(soup, "description"),
        "language": soup.html.get("lang", "") if soup.html else "",
    }
    if used_headless:
        metadata["fetched_via"] = "agent-browser"
    metadata = {k: v for k, v in metadata.items() if v}

    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, str(a["href"]))
        if href.startswith(("http://", "https://")):
            links.append(href)
    links = list(dict.fromkeys(links))[:50]

    doc: dict = {"metadata": metadata, "links": links[:30]}
    if formats is None or "markdown" in formats:
        doc["markdown"] = markdown
    if formats is None or "html" in formats:
        doc["html"] = str(work_soup)[: config.max_scrape * 2]
    return doc


def map_url(url: str, limit: int = 50) -> list[str]:
    import time

    for attempt in range(3):
        try:
            resp = requests.get(
                url, headers={"User-Agent": config.user_agent}, timeout=10
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                href = urljoin(url, str(a["href"]))
                if href.startswith(("http://", "https://")):
                    links.append(href)
            return list(dict.fromkeys(links))[:limit]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)
    return []  # unreachable
