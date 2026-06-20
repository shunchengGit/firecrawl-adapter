"""Request handler functions: pure logic, return response dicts."""
from __future__ import annotations

import logging
import threading
import time
import uuid

from .config import config
from .fetcher import bing_search, compile_search_query, map_url, scrape_url, searxng_search
from .jobs import cancel_job, crawl_worker, create_job, get_job

_log = logging.getLogger("adapter")

# Firecrawl source type → SearXNG category
_SOURCE_CATEGORY: dict[str, str] = {
    "web": "general",
    "news": "news",
    "images": "images",
}


def _map_sources_to_categories(sources: list | None) -> str:
    """Map Firecrawl `sources: [{type: "web"}, ...]` to SearXNG categories string."""
    if not sources:
        return config.searxng_categories
    cats: list[str] = []
    for s in sources:
        t = s.get("type", "web") if isinstance(s, dict) else str(s)
        if t in _SOURCE_CATEGORY:
            cats.append(_SOURCE_CATEGORY[t])
    return ",".join(cats) if cats else config.searxng_categories


def handle_search(body: dict) -> dict:
    q = body.get("query", "")
    if not q:
        return {"success": False, "error": "Missing query"}

    requested = body.get("limit", 5)
    limit = min(requested, config.max_search_results)
    language = body.get("lang") or body.get("language")
    categories = _map_sources_to_categories(body.get("sources"))

    # 1. Compile domain filters into the query (site: / -site: ops)
    include_domains = body.get("includeDomains") or []
    exclude_domains = body.get("excludeDomains") or []
    search_query = compile_search_query(q, include_domains, exclude_domains)

    # 2. Request 2× buffer to account for filtering / dedup loss
    fetch_limit = min(limit * 2, config.max_search_results * 2)

    results = searxng_search(
        search_query,
        limit=fetch_limit,
        categories=categories,
        language=language,
    )

    # 3. SearXNG 返回空 → Bing 兜底
    if not results:
        _log.info("SearXNG returned 0 results, falling back to Bing")
        bing_results = bing_search(q, limit=fetch_limit)
        if bing_results:
            results = bing_results

    # 4. Slice to exact limit
    results = results[:limit]

    return {
        "success": True,
        "data": {"web": results},
        "searchId": uuid.uuid4().hex,
    }


def handle_scrape(body: dict) -> dict:
    url = body.get("url", "")
    if not url:
        return {"success": False, "error": "Missing url"}
    only_main = body.get("onlyMainContent", body.get("only_main_content", False))
    formats = body.get("formats")
    if formats is None:
        scrape_opts = body.get("scrapeOptions", body.get("scrape_options", {}))
        formats = scrape_opts.get("formats") if isinstance(scrape_opts, dict) else None
    if isinstance(formats, str):
        formats = [formats]
    for attempt in range(3):
        try:
            doc = scrape_url(
                url,
                formats=formats,
                only_main=only_main,
                timeout=body.get("timeout", 15),
            )
            return {"success": True, "data": doc}
        except Exception as e:
            if attempt == 2:
                return {"success": False, "error": f"Scrape failed: {e}"}
            time.sleep(1)
    return {"success": False, "error": "Scrape failed"}


def handle_start_crawl(body: dict) -> dict:
    url = body.get("url", "")
    if not url:
        return {"success": False, "error": "Missing url"}
    job_id = create_job(url)
    threading.Thread(
        target=crawl_worker,
        args=(
            job_id,
            url,
            body.get("limit", 10),
            body.get("maxDiscoveryDepth", 1),
            body.get("includePaths"),
            body.get("excludePaths"),
        ),
        daemon=True,
    ).start()
    return {"success": True, "id": job_id, "url": url}


def handle_crawl_status(job_id: str, query: dict | None = None) -> dict:
    job = get_job(job_id)
    if not job:
        return {"success": False, "error": f"Job not found: {job_id}"}
    data = job.get("data", [])
    per_page = config.max_crawl_page_size
    raw_page = query.get("page", "1") if query else "1"
    try:
        page = max(1, int(raw_page))
    except (ValueError, TypeError):
        page = 1
    start = (page - 1) * per_page
    page_data = data[start : start + per_page]
    has_more = (start + per_page) < len(data)
    next_url = f"/v2/crawl/{job_id}?page={page + 1}" if has_more else None
    return {
        "success": True,
        "status": job.get("status"),
        "completed": job.get("completed"),
        "total": job.get("total"),
        "creditsUsed": 0,
        "expiresAt": None,
        "next": next_url,
        "data": page_data,
    }


def handle_cancel_crawl(job_id: str) -> dict:
    if cancel_job(job_id):
        return {"success": True, "status": "cancelled"}
    return {"success": False, "error": f"Job not found: {job_id}"}


def handle_extract(body: dict) -> dict:
    """Minimal extract — scrape listed URLs without AI processing."""
    urls = body.get("urls", [])
    if not urls:
        return {"success": False, "error": "Missing urls"}
    docs = []
    for url in urls[:5]:
        try:
            docs.append(scrape_url(url, formats=["markdown"]))
        except Exception as e:
            _log.warning("Extract failed for %s: %s", url, e)
            docs.append({"url": url, "markdown": "", "error": "fetch failed"})
    return {"success": True, "data": docs}


def handle_map(body: dict) -> dict:
    url = body.get("url", "")
    if not url:
        return {"success": False, "error": "Missing url"}
    try:
        return {"success": True, "links": map_url(url, limit=body.get("limit", 50))}
    except Exception as e:
        return {"success": False, "error": f"Map failed: {e}"}
