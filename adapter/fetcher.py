"""URL fetching: requests first, agent-browser headless fallback."""
from __future__ import annotations

import contextlib
import io
import json
import logging
import math
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import config
from .parser import extract_main, get_meta, html_to_markdown

_log = logging.getLogger("adapter")

_ANTI_BOT_KEYWORDS = ("_waf_", "captcha", "验证码", "请求存在异常", "限制本次访问")
_SOFT_NOT_FOUND_MARKERS = (
    "页面不存在",
    "页面已删除",
    "内容不存在",
    "page not found",
    "404 not found",
    "sorry, the page",
)
_RESTRICTED_MARKERS = (
    "访问受限",
    "登录后查看",
    "登录后继续",
    "please log in",
    "sign in to continue",
    "access denied",
    "security check",
)

_SEARXNG_PAGE_SIZE = 20  # SearXNG default results per page

_BING_SEARCH = "https://www.bing.com/search"

# 抓取有效性分类：接口成功 ≠ 拿到目标正文
SCRAPE_OK = "ok"
SCRAPE_PARTIAL = "partial"
SCRAPE_NOT_FOUND = "not_found"
SCRAPE_RESTRICTED = "restricted"
SCRAPE_INCOMPLETE = "incomplete"
SCRAPE_UNSUPPORTED = "unsupported"
SCRAPE_NETWORK_ERROR = "network_error"
SCRAPE_TIMEOUT = "timeout"

FAILURE_STATUSES = frozenset(
    {
        SCRAPE_NOT_FOUND,
        SCRAPE_RESTRICTED,
        SCRAPE_INCOMPLETE,
        SCRAPE_UNSUPPORTED,
        SCRAPE_NETWORK_ERROR,
        SCRAPE_TIMEOUT,
    }
)


@dataclass
class ScrapeResult:
    """内部抓取结果模型：不再用 Markdown 前缀传递失败状态。"""

    url: str
    final_url: str
    status: str
    document: dict | None = None
    detail: str = ""
    via: str = ""
    attempts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (SCRAPE_OK, SCRAPE_PARTIAL) and self.document is not None


# ---------------------------------------------------------------------------
# 搜索：query 编译、域名硬过滤、去重（T03）
# ---------------------------------------------------------------------------


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


def normalize_domain(domain: str) -> str:
    """把用户给出的域名约束规范化为裸 hostname（小写、去端口/路径/scheme）。"""
    d = str(domain).strip().lower()
    if "://" in d:
        d = urlparse(d).netloc
    d = d.split("/")[0].split("@")[-1].split(":")[0]
    return d.strip(".")


def _host_matches(host: str, domain: str) -> bool:
    """子域名匹配规则：example.com 匹配自身及 *.example.com。"""
    return host == domain or host.endswith("." + domain)


def _validate_result_url(url: object) -> str | None:
    """校验可返回 URL 的 scheme 和基本形状；不安全的结果不得作为有效链接。"""
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url


def normalize_url_key(url: str) -> str:
    """去重键：host 小写、去默认端口、去 fragment，保留 path 与 query。

    不合并不同 scheme 或仅“看起来相似”的页面，避免过度合并。
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    elif parsed.scheme == "https" and host.endswith(":443"):
        host = host[:-4]
    key = f"{parsed.scheme}://{host}{parsed.path or '/'}"
    if parsed.query:
        key += f"?{parsed.query}"
    return key


def filter_results(
    results: list[dict],
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """对搜索结果做 URL 校验、域名硬过滤（排除优先）与规范化去重。

    site: 只是上游提示，不是约束；这里按解析后的 hostname 兑现约束。
    """
    include = {normalize_domain(d) for d in (include_domains or []) if str(d).strip()}
    include.discard("")
    exclude = {normalize_domain(d) for d in (exclude_domains or []) if str(d).strip()}
    exclude.discard("")

    filtered: list[dict] = []
    seen_keys: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = _validate_result_url(item.get("url"))
        if url is None:
            continue
        host = normalize_domain(urlparse(url).netloc)
        if exclude and any(_host_matches(host, d) for d in exclude):
            continue
        if include and not any(_host_matches(host, d) for d in include):
            continue
        key = normalize_url_key(url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cleaned = {k: v for k, v in item.items() if not k.startswith("_")}
        cleaned["url"] = url
        # 内部诊断字段保留在独立键中，不进入公共响应
        diagnostics = {k: v for k, v in item.items() if k.startswith("_")}
        if diagnostics:
            cleaned["_diag"] = diagnostics
        filtered.append(cleaned)
    return filtered


def strip_internal_fields(results: list[dict]) -> list[dict]:
    """输出前剥离内部字段（引擎来源、打分明细等）。"""
    return [{k: v for k, v in item.items() if not k.startswith("_")} for item in results]


# ---------------------------------------------------------------------------
# 搜索引擎
# ---------------------------------------------------------------------------


def bing_search(query: str, limit: int = 10) -> list[dict]:
    """Search Bing (HTML scrape) as a fallback when SearXNG returns empty.

    Bing is directly accessible from China, no proxy needed.
    Returns empty list on any error (graceful degradation).
    调用方必须传入已编译域名过滤的 query，与 SearXNG 路径保持一致。
    """
    if limit <= 0:
        return []

    results: list[dict] = []
    try:
        params = urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(
            f"{_BING_SEARCH}?{params}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read()

        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select("li.b_algo")[:limit]:
            link = item.select_one("h2 a")
            snippet = item.select_one(".b_caption p, .b_caption, p")
            if not link:
                continue

            title = link.get_text(strip=True)
            url: str = link["href"]  # type: ignore[assignment]
            # Bing wraps results in its own redirect URL
            if url and not url.startswith("http"):
                parsed = urlparse(url)
                if "url=" in url or "r=" in url:
                    from urllib.parse import parse_qs, unquote
                    try:
                        for key in ("url", "r", "u"):
                            val = parse_qs(parsed.query).get(key)
                            if val and val[0].startswith("http"):
                                url = unquote(val[0])
                                break
                    except Exception:
                        url = link["href"]  # type: ignore[assignment]
                else:
                    url = urljoin("https://www.bing.com", url)

            results.append({
                "title": title or query,
                "url": url,
                "content": snippet.get_text(separator=" ", strip=True) if snippet else "",
                "_engines": ["bing"],
            })

        _log.info("Bing returned %d results for %r", len(results), query[:60])
    except Exception as e:
        _log.warning("Bing search failed (%s), returning empty", e)

    return results[:limit]


# 与 searxng/settings.yml.template 启用清单保持一致；仅当需要按禁用列表
# 做减法而 SEARXNG_ENGINES 未显式配置时作为基准
_DEFAULT_ENGINES = "360search,quark,bing,wikipedia,fynd,yandex,presearch"


def _effective_engines(engines: str | None) -> str | None:
    """应用引擎隔离配置（T02）：只影响默认引擎集，不改显式参数。"""
    if engines is not None:
        return engines or None
    configured = config.searxng_engines
    disabled = {
        e.strip().lower() for e in config.searxng_disabled_engines.split(",") if e.strip()
    }
    if not disabled:
        return configured or None
    base = configured or _DEFAULT_ENGINES
    enabled = [e for e in base.split(",") if e.strip().lower() not in disabled]
    if len(enabled) != len(base.split(",")):
        removed = sorted(disabled & {e.strip().lower() for e in base.split(",")})
        _log.info("Engines disabled by config: %s", ",".join(removed))
    return ",".join(enabled) or None


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

    每条结果内部保留来源引擎与上游分数（``_engines`` / ``_score`` 键），
    供诊断与重排使用；公共响应前需经 strip_internal_fields 剥离。
    """
    if limit <= 0:
        return []

    engines = _effective_engines(engines)
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

        unresponsive = data.get("unresponsive_engines") or []
        if unresponsive:
            # 错误/验证码与“正常零结果”分开记录
            _log.warning("SearXNG unresponsive engines for %r: %s", query[:60], unresponsive)

        page_results = data.get("results", [])
        if not page_results:
            break

        for item in page_results:
            all_results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "_engines": item.get("engines", []),
                    "_score": item.get("score", 0),
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


# ---------------------------------------------------------------------------
# 抓取有效性分类（T06）
# ---------------------------------------------------------------------------


def _visible_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup.get_text(separator=" ", strip=True)


def _is_likely_blocked(html_raw: str) -> bool:
    """requests 路径的疑似受阻启发式：短页面或短文本反机器人页 → 浏览器回退。

    关键词命中需同时文本较短，长文讨论 captcha 不应触发回退。
    """
    soup = BeautifulSoup(html_raw, "html.parser")
    body_text = _visible_text(soup)
    if len(body_text) < 500:
        return True
    lower = html_raw.lower()
    return any(kw in lower for kw in _ANTI_BOT_KEYWORDS) and len(body_text) < 1500


def _looks_like_spa_shell(soup: BeautifulSoup, text: str) -> bool:
    """识别“页面壳已返回但正文未渲染”的 SPA 场景。"""
    if len(text) >= 150:
        return False
    if soup.find("div", id=("root", "app", "__next", "__nuxt")):
        return True
    return bool(soup.find("script", src=True) and len(text) < 80)


def classify_html(html_raw: str, http_status: int | None = None) -> tuple[str, str]:
    """区分“拿到内容”和“拿到目标正文”。

    返回 (status, detail)。只看页面自身特征，不发起网络请求。
    短页面不直接判失败：合法短页面返回 ok；疑似未渲染的 SPA 壳返回 incomplete。
    """
    if http_status in (404, 410):
        return SCRAPE_NOT_FOUND, f"HTTP {http_status}"
    if http_status in (401, 403):
        return SCRAPE_RESTRICTED, f"HTTP {http_status}"

    soup = BeautifulSoup(html_raw, "html.parser")
    text = _visible_text(soup)
    lower = html_raw.lower()

    if len(text) < 2000 and any(m in lower for m in _SOFT_NOT_FOUND_MARKERS):
        return SCRAPE_NOT_FOUND, "page reports content missing (soft 404)"

    restricted = any(kw in lower for kw in _ANTI_BOT_KEYWORDS) or any(
        m in lower for m in _RESTRICTED_MARKERS
    )
    if restricted and len(text) < 1500:
        return SCRAPE_RESTRICTED, "anti-bot or access-restriction page"

    if _looks_like_spa_shell(soup, text):
        return SCRAPE_INCOMPLETE, "page shell without rendered content"

    return SCRAPE_OK, "short page" if len(text) < 500 else ""


# ---------------------------------------------------------------------------
# PDF（T10）
# ---------------------------------------------------------------------------


def _is_pdf(content_type: str, body: bytes) -> bool:
    """按 Content-Type 与文件签名识别 PDF，不只看 URL 后缀。"""
    if "pdf" in (content_type or "").lower():
        return True
    return body[:5] == b"%PDF-"


def _pdf_to_result(data: bytes, url: str, final_url: str) -> ScrapeResult:
    """解析文本型 PDF 为 Markdown；扫描/加密/损坏分别归类。"""
    if len(data) > config.max_pdf_bytes:
        return ScrapeResult(
            url=url,
            final_url=final_url,
            status=SCRAPE_UNSUPPORTED,
            detail=f"PDF too large: {len(data)} bytes (max {config.max_pdf_bytes})",
        )

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        return ScrapeResult(
            url=url,
            final_url=final_url,
            status=SCRAPE_UNSUPPORTED,
            detail=f"PDF parse failed: {e}",
        )

    if reader.is_encrypted:
        with contextlib.suppress(Exception):
            reader.decrypt("")
        if reader.is_encrypted:
            return ScrapeResult(
                url=url,
                final_url=final_url,
                status=SCRAPE_RESTRICTED,
                detail="PDF is encrypted",
            )

    pages: list[str] = []
    total_pages = len(reader.pages)
    truncated = False
    for i, page in enumerate(reader.pages):
        if i >= config.max_pdf_pages:
            truncated = True
            break
        try:
            pages.append((page.extract_text() or "").strip())
        except Exception:
            pages.append("")

    body = "\n\n".join(f"[page {i + 1}]\n{text}" for i, text in enumerate(pages) if text)

    detail = ""
    status = SCRAPE_OK
    if not body.strip():
        status = SCRAPE_PARTIAL
        detail = "PDF has no extractable text (likely scanned; OCR not supported)"
    elif truncated:
        status = SCRAPE_PARTIAL
        detail = f"PDF truncated at {config.max_pdf_pages} of {total_pages} pages"

    document = {
        "metadata": {
            "title": url,
            "url": url,
            "sourceURL": final_url,
            "contentType": "application/pdf",
            "pdfPages": total_pages,
            "scrapeStatus": status,
        },
        "links": [],
        "markdown": body[: config.max_scrape],
    }
    return ScrapeResult(
        url=url,
        final_url=final_url,
        status=status,
        document=document,
        detail=detail,
        via="requests",
        attempts=["requests"],
    )


# ---------------------------------------------------------------------------
# agent-browser headless 回退（T07：等待动态正文就绪）
# ---------------------------------------------------------------------------


def find_agent_browser() -> str | None:
    """Locate the agent-browser CLI binary."""
    return shutil.which("agent-browser")


# 页面变更观察：记录最后一次 DOM 变更时间，用于判断“正文还在加载”
_OBSERVER_JS = (
    "window.__adapterLastMutation=Date.now();"
    "new MutationObserver(function(){window.__adapterLastMutation=Date.now();})"
    ".observe(document.documentElement,{childList:true,subtree:true,characterData:true});"
    "'ok'"
)
_PROBE_JS = (
    "JSON.stringify({"
    "t:(document.body?document.body.innerText:'').length,"
    "m:window.__adapterLastMutation||0})"
)


def _browser_eval(agent_bin: str, session: str, expr: str, timeout_s: float) -> str:
    result = subprocess.run(
        [agent_bin, "--session", session, "eval", expr],
        capture_output=True,
        text=True,
        timeout=max(1, timeout_s),
    )
    if result.returncode != 0:
        raise RuntimeError(f"agent-browser eval exit {result.returncode}: {result.stderr[:300]}")
    return result.stdout.strip()


def _parse_eval_string(raw: str) -> str:
    """agent-browser eval 输出可能是 JSON 包裹的字符串。"""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, dict):
            value = parsed.get("result", parsed.get("value", raw))
            if isinstance(value, str):
                return value
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def _wait_for_content(
    agent_bin: str,
    session: str,
    deadline: float,
    wait_ms: int = 0,
) -> bool:
    """等待动态正文就绪，而不是 open 后立即读取。

    判据：DOM 静默（最近 1.5s 无变更）且文本达到一定规模；观察器不可用时
    退化为文本长度稳定性判断。均受总 deadline 约束。返回 True 表示就绪，
    False 表示预算耗尽（调用方应标注 incomplete/timeout）。
    """
    start = time.monotonic()
    budget = deadline - start
    # 短页逃逸：DOM 长时间静默说明“页就是这么短”，但逃逸必须足够晚，
    # 否则会抢在延迟注入（实测 10 秒级）之前把导航壳当正文
    short_escape = min(20.0, max(6.0, budget * 0.5))

    # 安装 MutationObserver（best effort，旧版本失败则退化为文本稳定性）
    observer_ok = False
    with contextlib.suppress(Exception):
        _browser_eval(agent_bin, session, _OBSERVER_JS, timeout_s=5)
        observer_ok = True

    last_len = -1
    stable_polls = 0
    min_elapsed = max(2.0, wait_ms / 1000.0)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 2:
            return False

        text_len = 0
        last_mutation_ms = 0
        try:
            raw = _browser_eval(agent_bin, session, _PROBE_JS, timeout_s=min(10, remaining))
            probe = json.loads(_parse_eval_string(raw))
            if isinstance(probe, str):
                probe = json.loads(probe)
            text_len = int(probe.get("t", 0))
            last_mutation_ms = int(probe.get("m", 0))
        except Exception:
            pass

        elapsed = time.monotonic() - start
        quiet_ms = time.time() * 1000 - last_mutation_ms if last_mutation_ms else 0

        if text_len == last_len:
            stable_polls += 1
        else:
            stable_polls = 0
        last_len = text_len

        if elapsed >= min_elapsed:
            if observer_ok and last_mutation_ms:
                quiet = quiet_ms > 1500
                # 正文达到一定规模且 DOM 静默 → 就绪
                if quiet and text_len >= 150:
                    return True
                # 合法短页面：DOM 长时间静默后不再空等
                if quiet and elapsed >= short_escape:
                    return True
            else:
                # 退化判据：文本长度连续稳定
                if stable_polls >= 3 and text_len >= 150:
                    return True
                if stable_polls >= 3 and elapsed >= short_escape:
                    return True

        time.sleep(min(0.5, max(0.1, deadline - time.monotonic() - 1)))


def scrape_url_headless(
    url: str,
    timeout: float = 30,
    wait_ms: int = 0,
) -> tuple[str, str, bool]:
    """agent-browser fallback for anti-bot-blocked / JS-rendered pages.

    *timeout* 是总工作预算（秒，单调时钟 deadline），不是导航超时。
    返回 (final_url, html, timed_out)。timed_out=True 表示正文等待预算耗尽，
    调用方应据此标注 incomplete，而不是把导航壳当完整正文。
    Raises Exception on failure — caller should catch and handle.
    """
    agent_bin = find_agent_browser()
    if not agent_bin:
        raise RuntimeError("agent-browser not found in PATH")

    deadline = time.monotonic() + timeout
    session = f"adapter_{uuid.uuid4().hex[:8]}"

    try:
        result = subprocess.run(
            [agent_bin, "--session", session, "open", url],
            capture_output=True,
            text=True,
            timeout=max(5, deadline - time.monotonic()),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"agent-browser open exit {result.returncode}: {result.stderr[:500]}"
            )

        timed_out = not _wait_for_content(agent_bin, session, deadline, wait_ms=wait_ms)

        final_url = url
        try:
            result = subprocess.run(
                [agent_bin, "--session", session, "get", "url", "--json"],
                capture_output=True,
                text=True,
                timeout=max(1, min(10, deadline - time.monotonic())),
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    final_url = data.get("data", {}).get("url", url) or url
        except Exception:
            pass

        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("headless scrape exceeded time budget before content read")
        html_raw = _browser_eval(
            agent_bin,
            session,
            "document.documentElement.outerHTML",
            timeout_s=min(15, remaining),
        )

        return final_url, _parse_eval_string(html_raw), timed_out
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"headless scrape timed out: {e}") from e
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


# ---------------------------------------------------------------------------
# scrape 主链路（T06/T07/T10）
# ---------------------------------------------------------------------------


def _build_document(
    url: str,
    final_url: str,
    html_raw: str,
    formats: list[str] | None,
    only_main: bool,
    via: str,
    status: str,
) -> dict:
    soup = BeautifulSoup(html_raw, "html.parser")

    # 先提取链接，再清理 header/footer/nav —— 否则导航链接全部丢失
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, str(a["href"]))
        if href.startswith(("http://", "https://")):
            links.append(href)
    links = list(dict.fromkeys(links))[:50]

    title = (soup.title.string or "").strip() if soup.title else ""
    title = title or url

    metadata: dict = {
        "title": title,
        "url": url,
        "sourceURL": final_url,
        "description": get_meta(soup, "description"),
        "language": soup.html.get("lang", "") if soup.html else "",
        "scrapeStatus": status,
    }
    if via == "agent-browser":
        metadata["fetched_via"] = "agent-browser"
    metadata = {k: v for k, v in metadata.items() if v not in ("", None)}

    for t in soup(["script", "style", "footer", "header", "noscript"]):
        t.decompose()

    work_soup = extract_main(soup) if only_main else soup
    markdown = html_to_markdown(str(work_soup), config.max_scrape)

    doc: dict = {"metadata": metadata, "links": links[:30]}
    if formats is None or "markdown" in formats:
        doc["markdown"] = markdown
    if formats is None or "html" in formats:
        doc["html"] = str(work_soup)[: config.max_scrape * 2]
    return doc


def scrape_url_result(
    url: str,
    formats: list[str] | None = None,
    only_main: bool = False,
    timeout_s: float = 30.0,
    wait_ms: int = 0,
) -> ScrapeResult:
    """抓取 URL 并做有效性分类。

    requests 优先；疑似受阻 / 受限 / 未渲染 / 网络失败时回退 agent-browser。
    两条路径都做有效性复核：浏览器打开成功不等于抓取成功。
    """
    deadline = time.monotonic() + timeout_s
    final_url = url
    html_raw = ""
    used_headless = False
    headless_timed_out = False
    attempts: list[str] = []
    requests_error = ""
    http_status: int | None = None

    try:
        attempts.append("requests")
        resp = requests.get(
            url,
            headers={"User-Agent": config.user_agent},
            timeout=max(1, min(10, deadline - time.monotonic())),
            allow_redirects=True,
        )
        final_url = resp.url
        http_status = resp.status_code
        content_type = resp.headers.get("content-type", "")

        if _is_pdf(content_type, resp.content):
            result = _pdf_to_result(resp.content, url, final_url)
            result.attempts = attempts
            return result

        if resp.status_code in (404, 410):
            # 硬 404/410 是确定性结论，不再浪费浏览器预算
            return ScrapeResult(
                url=url,
                final_url=final_url,
                status=SCRAPE_NOT_FOUND,
                detail=f"HTTP {resp.status_code}",
                via="requests",
                attempts=attempts,
            )

        resp.encoding = resp.apparent_encoding or "utf-8"
        html_raw = resp.text
        # 401/403/429/5xx、疑似受阻、疑似未渲染都交给浏览器复核
        if (
            resp.status_code in (401, 403, 429)
            or resp.status_code >= 500
            or _is_likely_blocked(html_raw)
        ):
            raise ValueError(f"requests path suspicious (HTTP {resp.status_code})")
    except Exception as e:
        _log.warning("requests.get failed for %s (%s), trying agent-browser", url, e)
        requests_error = str(e)
        html_raw = ""

    if not html_raw:
        try:
            attempts.append("agent-browser")
            final_url, html_raw, headless_timed_out = scrape_url_headless(
                url,
                timeout=max(1, deadline - time.monotonic()),
                wait_ms=wait_ms,
            )
            used_headless = True
        except TimeoutError as e:
            _log.warning("agent-browser timed out for %s: %s", url, e)
            return ScrapeResult(
                url=url,
                final_url=final_url,
                status=SCRAPE_TIMEOUT,
                detail=str(e),
                attempts=attempts,
            )
        except Exception as e:
            _log.warning("agent-browser also failed for %s: %s", url, e)
            return ScrapeResult(
                url=url,
                final_url=final_url,
                status=SCRAPE_NETWORK_ERROR,
                detail=f"requests: {requests_error or 'rejected'}; headless: {e}",
                attempts=attempts,
            )

    status, detail = classify_html(html_raw, None if used_headless else http_status)
    if headless_timed_out and status in (SCRAPE_OK, SCRAPE_INCOMPLETE):
        # 等待预算耗尽：即便拿到内容也明确标注不完整，不冒充完整正文
        status, detail = (
            (SCRAPE_INCOMPLETE, "content wait budget exhausted")
            if len(html_raw) < 20000
            else (SCRAPE_PARTIAL, "content wait budget exhausted; returning current content")
        )

    if status in FAILURE_STATUSES:
        return ScrapeResult(
            url=url,
            final_url=final_url,
            status=status,
            detail=detail,
            via="agent-browser" if used_headless else "requests",
            attempts=attempts,
        )

    via = "agent-browser" if used_headless else "requests"
    document = _build_document(url, final_url, html_raw, formats, only_main, via, status)
    return ScrapeResult(
        url=url,
        final_url=final_url,
        status=status,
        document=document,
        detail=detail,
        via=via,
        attempts=attempts,
    )


def scrape_url(
    url: str,
    formats: list[str] | None = None,
    only_main: bool = False,
    timeout: float = 15,
) -> dict:
    """Fetch a URL → Document dict with markdown / html / metadata.

    兼容包装：crawl/extract 沿用 dict 返回；失败状态写入
    ``metadata.scrapeStatus``，不再只靠 Markdown 前缀判断。
    *timeout* 单位为秒（内部预算）。
    """
    result = scrape_url_result(url, formats=formats, only_main=only_main, timeout_s=timeout)
    if result.document is not None:
        return result.document
    return {
        "metadata": {
            "title": url,
            "url": url,
            "sourceURL": result.final_url,
            "scrapeStatus": result.status,
            "scrapeDetail": result.detail,
        },
        "links": [],
        "markdown": f"[fetch failed: {result.detail or result.status}]",
    }


def map_url(url: str, limit: int = 50) -> list[str]:
    for attempt in range(3):
        try:
            resp = requests.get(
                url, headers={"User-Agent": config.user_agent}, timeout=10
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                # 用最终 URL 拼接相对链接，重定向后不产生坏链
                href = urljoin(resp.url, str(a["href"]))
                if href.startswith(("http://", "https://")):
                    links.append(href)
            return list(dict.fromkeys(links))[:limit]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)
    return []  # unreachable
