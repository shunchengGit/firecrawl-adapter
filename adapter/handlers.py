"""Request handler functions: pure logic, return response dicts."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from .config import Config, config
from .fetcher import bing_search, compile_search_query, map_url, scrape_url, searxng_search
from .jobs import (
    CrawlCapacityError,
    CrawlDispatcherStoppedError,
    CrawlRequest,
    cancel_job,
    get_job,
    submit_crawl,
)
from .parser import compile_path_patterns

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


class CrawlValidationError(ValueError):
    pass


def _crawl_integer(body: dict, key: str, default: int, maximum: int) -> int:
    value = body.get(key, default)
    if type(value) is not int:
        raise CrawlValidationError(f"{key} must be an integer")
    minimum = 0 if key == "maxDiscoveryDepth" else 1
    if not minimum <= value <= maximum:
        raise CrawlValidationError(f"{key} must be between {minimum} and {maximum}")
    return value


def _crawl_paths(body: dict, key: str, settings: Config) -> tuple[str, ...]:
    if key not in body:
        return ()
    value = body[key]
    if not isinstance(value, list):
        raise CrawlValidationError(f"{key} must be a list")
    if len(value) > settings.max_crawl_path_filters:
        raise CrawlValidationError(
            f"{key} must contain at most {settings.max_crawl_path_filters} patterns"
        )
    patterns = []
    for pattern in value:
        if not isinstance(pattern, str) or not pattern:
            raise CrawlValidationError(f"{key} patterns must be non-empty strings")
        if len(pattern) > settings.max_crawl_path_length:
            raise CrawlValidationError(
                f"{key} patterns must be at most {settings.max_crawl_path_length} characters"
            )
        if not pattern.startswith("/"):
            raise CrawlValidationError(f"{key} patterns must start with /")
        patterns.append(pattern)
    return tuple(patterns)


def parse_crawl_request(body: dict, *, settings: Config = config) -> CrawlRequest:
    url = body.get("url")
    if not isinstance(url, str) or not url.strip():
        raise CrawlValidationError("Missing url")
    limit = _crawl_integer(
        body, "limit", settings.crawl_default_limit, settings.max_crawl_limit
    )
    max_depth = _crawl_integer(
        body,
        "maxDiscoveryDepth",
        settings.crawl_default_depth,
        settings.max_crawl_depth,
    )
    include_paths = compile_path_patterns(_crawl_paths(body, "includePaths", settings))
    exclude_paths = compile_path_patterns(_crawl_paths(body, "excludePaths", settings))
    return CrawlRequest(
        url=url.strip(),
        limit=limit,
        max_depth=max_depth,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
    )


def handle_start_crawl(body: dict) -> dict:
    try:
        request = parse_crawl_request(body)
        job_id = submit_crawl(request)
    except CrawlValidationError as exc:
        return {"success": False, "code": "invalid_crawl_request", "error": str(exc)}
    except CrawlCapacityError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}
    except CrawlDispatcherStoppedError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}
    return {"success": True, "id": job_id, "url": request.url}


def _expires_at(finished_at: float | None) -> str | None:
    if finished_at is None:
        return None
    expires = datetime.fromtimestamp(
        finished_at + config.job_ttl_seconds, tz=timezone.utc
    )
    return expires.isoformat().replace("+00:00", "Z")


def handle_crawl_status(job_id: str, query: dict | None = None) -> dict:
    job = get_job(job_id)
    if not job:
        return {"success": False, "error": f"Job not found: {job_id}"}
    data = job.data
    per_page = config.max_crawl_page_size
    raw_page = query.get("page", "1") if query else "1"
    try:
        page = max(1, int(raw_page))
    except (ValueError, TypeError):
        page = 1
    start = (page - 1) * per_page
    page_data = list(data[start : start + per_page])
    has_more = (start + per_page) < len(data)
    next_url = f"/v2/crawl/{job_id}?page={page + 1}" if has_more else None
    response = {
        "success": True,
        "status": job.status,
        "completed": job.completed,
        "total": job.total,
        "discovered": job.discovered,
        "queued": job.queued,
        "failed": job.failed,
        "skipped": job.skipped,
        "creditsUsed": 0,
        "expiresAt": _expires_at(job.finished_at),
        "next": next_url,
        "data": page_data,
    }
    if job.error:
        response["error"] = job.error
    return response


def handle_cancel_crawl(job_id: str) -> dict:
    job = cancel_job(job_id)
    if job:
        return {"success": True, "status": job.status}
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
