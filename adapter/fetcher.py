"""URL fetching: requests first, agent-browser headless fallback."""
from __future__ import annotations

import contextlib
import json
import logging
import shutil
import subprocess
import urllib.parse
import urllib.request
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import config
from .parser import extract_main, get_meta, html_to_markdown

_log = logging.getLogger("adapter")

_ANTI_BOT_KEYWORDS = ("_waf_", "captcha", "验证码", "请求存在异常", "限制本次访问")


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

    try:
        result = subprocess.run(
            [agent_bin, "open", url],
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
                [agent_bin, "get", "url", "--json"],
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
            [agent_bin, "eval", "document.documentElement.outerHTML"],
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
        # 每次抓取后 close，确保 cookie 落盘到 session 文件，daemon 状态不漂移。
        # 代价是下次抓取要冷启动 Chrome（数秒）。
        with contextlib.suppress(Exception):
            subprocess.run(
                [agent_bin, "close", "--all"],
                capture_output=True,
                text=True,
                timeout=10,
            )


def searxng_search(query: str, limit: int = 5) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query, "format": "json", "categories": "general"}
    )
    req = urllib.request.Request(
        f"{config.searxng_base}/search?{params}",
        headers={"User-Agent": config.user_agent},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    results = []
    for item in data.get("results", [])[:limit]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
        )
    return results


def check_searxng() -> bool:
    """Quick liveness probe for SearXNG. Returns True if reachable."""
    try:
        req = urllib.request.Request(
            f"{config.searxng_base}/search?q=test&format=json",
            headers={"User-Agent": config.user_agent},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
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
