"""Tests for handler-level validation logic (no network calls)."""
from __future__ import annotations

import dataclasses
import threading
from unittest.mock import patch

from adapter import handlers
from adapter.config import config
from adapter.jobs import CrawlDispatcher, reset_crawl_dispatcher_for_tests


def test_search_missing_query():
    res = handlers.handle_search({})
    assert res["success"] is False
    assert "Missing query" in res["error"]


def test_search_returns_search_id():
    """Search response includes a searchId for feedback tracking."""
    with patch("adapter.handlers.searxng_search", return_value=[]):
        res = handlers.handle_search({"query": "test", "limit": 3})
    assert res["success"] is True
    assert "searchId" in res
    assert isinstance(res["searchId"], str)
    assert len(res["searchId"]) == 32  # uuid4 hex


def test_search_with_language():
    """language / lang parameter is passed through to searxng_search."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({"query": "test", "language": "zh-CN"})
        assert mock_search.call_args[1]["language"] == "zh-CN"

    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({"query": "test", "lang": "en"})
        assert mock_search.call_args[1]["language"] == "en"


def test_search_limit_capped():
    """fetch_limit is capped to 2× max_search_results (buffer ceiling)."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({"query": "test", "limit": 9999})
        from adapter.config import config
        fetch_limit = mock_search.call_args[1]["limit"]
        # fetch_limit = min(9999, max) × 2, capped at max × 2
        assert fetch_limit == config.max_search_results * 2


def test_search_sources_to_categories():
    """Firecrawl sources are mapped to SearXNG categories."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({
            "query": "test",
            "sources": [{"type": "web"}, {"type": "news"}],
        })
    assert mock_search.call_args[1]["categories"] == "general,news"

    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({
            "query": "test",
            "sources": [{"type": "images"}],
        })
    assert mock_search.call_args[1]["categories"] == "images"


def test_search_no_sources_uses_default():
    """When no sources provided, uses config default categories."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({"query": "test"})
    from adapter.config import config
    assert mock_search.call_args[1]["categories"] == config.searxng_categories


def test_search_query_compile_domains():
    """Domain filters are compiled into the query via compile_search_query."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = ["r1", "r2"]
        handlers.handle_search({
            "query": "Python",
            "includeDomains": ["docs.python.org"],
            "excludeDomains": ["zhihu.com"],
            "limit": 5,
        })
        compiled_q = mock_search.call_args[0][0]
        assert "site:docs.python.org" in compiled_q
        assert "-site:zhihu.com" in compiled_q
        assert "Python" in compiled_q


def test_search_buffer_limit():
    """SearXNG is queried with 2× limit as buffer."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = ["a"] * 5
        handlers.handle_search({"query": "test", "limit": 5})
        # fetch_limit = min(5*2, max_search_results*2)
        fetch_limit = mock_search.call_args[1]["limit"]
        assert fetch_limit >= 5  # at least requested
        assert fetch_limit <= 5 * 2  # at most 2×


def test_compile_search_query():
    """Unit test for the query compiler."""
    from adapter.fetcher import compile_search_query

    # No domains
    assert compile_search_query("test") == "test"
    assert compile_search_query("test", None, None) == "test"
    assert compile_search_query("test", [], []) == "test"

    # Include only
    q = compile_search_query("Python", ["docs.python.org", "python.org"])
    assert q == "Python (site:docs.python.org OR site:python.org)"

    # Exclude only
    q = compile_search_query("Python", None, ["zhihu.com"])
    assert q == "Python -site:zhihu.com"

    # Both
    q = compile_search_query("Python", ["docs.python.org"], ["zhihu.com"])
    assert "site:docs.python.org" in q
    assert "-site:zhihu.com" in q
    assert q.startswith("Python")


def test_map_sources_empty_types_ignored():
    """Unknown source types are silently ignored in category mapping."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({
            "query": "test",
            "sources": [{"type": "web"}, {"type": "unknown"}],
        })
    assert mock_search.call_args[1]["categories"] == "general"


def test_scrape_missing_url():
    res = handlers.handle_scrape({})
    assert res["success"] is False
    assert "Missing url" in res["error"]


# T03: 域名硬约束与去重


def test_search_include_domains_hard_filtered():
    """includeDomains 是本地硬约束，不只是上游 site: 提示。"""
    mock_results = [
        {"title": "uv pip compile docs", "url": "https://docs.astral.sh/uv/pip/compile/", "content": "uv pip compile"},
        {"title": "uv index", "url": "https://uvi.today/uv-index-la", "content": "uv pip compile"},
    ]
    with patch("adapter.handlers.searxng_search", return_value=mock_results):
        res = handlers.handle_search({
            "query": "uv pip compile",
            "includeDomains": ["docs.astral.sh"],
            "limit": 5,
        })
    urls = [r["url"] for r in res["data"]["web"]]
    assert urls == ["https://docs.astral.sh/uv/pip/compile/"]


def test_search_dedupes_and_strips_internal_fields():
    mock_results = [
        {"title": "uv pip compile docs", "url": "https://docs.astral.sh/uv/pip/compile/", "content": "uv pip compile", "_engines": ["yandex"]},
        {"title": "dup", "url": "https://docs.astral.sh/uv/pip/compile/#top", "content": "uv pip compile", "_engines": ["bing"]},
    ]
    with patch("adapter.handlers.searxng_search", return_value=mock_results):
        res = handlers.handle_search({"query": "uv pip compile", "limit": 5})
    web = res["data"]["web"]
    assert len(web) == 1
    assert "_engines" not in web[0]
    assert "_diag" not in web[0]


def test_search_bing_fallback_uses_compiled_query():
    """Bing fallback 必须使用与 SearXNG 相同的编译 query，不丢域名约束。"""
    with (
        patch("adapter.handlers.searxng_search", return_value=[]),
        patch("adapter.handlers.bing_search", return_value=[]) as mock_bing,
    ):
        handlers.handle_search({
            "query": "uv pip compile",
            "includeDomains": ["docs.astral.sh"],
            "limit": 5,
        })
    assert mock_bing.called
    assert "site:docs.astral.sh" in mock_bing.call_args[0][0]


# T05: 有限补搜


def test_search_supplementary_round_on_low_quality():
    """首轮结果无关时触发一次补搜；补搜 query 保留域名约束。"""
    junk = [{"title": "unrelated thing", "url": "https://x.example.com/", "content": "nothing"}]
    good = [{
        "title": "agent-browser sessions",
        "url": "https://agent-browser.dev/sessions",
        "content": "agent-browser session-name cookie persistence",
    }]
    with patch("adapter.handlers.searxng_search", side_effect=[junk, good]) as mock_search:
        res = handlers.handle_search({
            "query": "agent-browser session-name cookie persistence",
            "limit": 3,
        })
    assert mock_search.call_count == 2
    # 补搜变体带引号精确匹配
    assert '"agent-browser"' in mock_search.call_args_list[1][0][0]
    assert res["data"]["web"][0]["url"] == "https://agent-browser.dev/sessions"


def test_search_no_supplementary_round_when_quality_sufficient():
    good = [
        {
            "title": "agent-browser sessions",
            "url": f"https://agent-browser.dev/sessions-{i}",
            "content": "agent-browser session-name cookie persistence",
        }
        for i in range(3)
    ]
    with patch("adapter.handlers.searxng_search", return_value=good) as mock_search:
        handlers.handle_search({
            "query": "agent-browser session-name cookie persistence",
            "limit": 3,
        })
    assert mock_search.call_count == 1


# T11: search + scrapeOptions 组合模式


def _scrape_result(status, markdown=None, detail=""):
    from adapter.fetcher import ScrapeResult

    doc = None
    if markdown is not None:
        doc = {"markdown": markdown, "metadata": {"scrapeStatus": status}, "links": []}
    return ScrapeResult(url="u", final_url="u", status=status, document=doc, detail=detail)


def test_search_scrape_options_tries_next_candidate_on_failure():
    candidates = [
        {"title": "agent-browser sessions a", "url": "https://agent-browser.dev/a", "content": "agent-browser session-name"},
        {"title": "agent-browser sessions b", "url": "https://agent-browser.dev/b", "content": "agent-browser session-name"},
    ]
    scrape_side_effects = [
        _scrape_result("restricted", detail="login required"),
        _scrape_result("ok", markdown="有效正文"),
    ]
    with (
        patch("adapter.handlers.searxng_search", return_value=candidates),
        patch("adapter.handlers.scrape_url_result", side_effect=scrape_side_effects) as mock_scrape,
    ):
        res = handlers.handle_search({
            "query": "agent-browser session-name",
            "limit": 2,
            "scrapeOptions": {"formats": ["markdown"]},
        })
    assert mock_scrape.call_count == 2
    first, second = res["data"]["web"]
    assert first["scrapeStatus"] == "restricted"
    assert first["scrapeError"] == "login required"
    assert second["markdown"] == "有效正文"


def test_search_scrape_options_stops_after_first_valid():
    candidates = [
        {"title": "agent-browser sessions a", "url": "https://agent-browser.dev/a", "content": "agent-browser session-name"},
        {"title": "agent-browser sessions b", "url": "https://agent-browser.dev/b", "content": "agent-browser session-name"},
    ]
    with (
        patch("adapter.handlers.searxng_search", return_value=candidates),
        patch(
            "adapter.handlers.scrape_url_result",
            return_value=_scrape_result("ok", markdown="有效正文"),
        ) as mock_scrape,
    ):
        res = handlers.handle_search({
            "query": "agent-browser session-name",
            "limit": 2,
            "scrapeOptions": {},
        })
    assert mock_scrape.call_count == 1
    assert res["data"]["web"][0]["markdown"] == "有效正文"


# T06/T07: scrape 失败映射与毫秒超时


def test_scrape_failure_returns_identifiable_code():
    with patch(
        "adapter.handlers.scrape_url_result",
        return_value=_scrape_result("not_found", detail="HTTP 404"),
    ):
        res = handlers.handle_scrape({"url": "https://example.com/gone"})
    assert res["success"] is False
    assert res["code"] == "page_not_found"
    assert "404" in res["error"]


def test_scrape_partial_content_returns_warning():
    with patch(
        "adapter.handlers.scrape_url_result",
        return_value=_scrape_result("partial", markdown="部分内容", detail="truncated"),
    ):
        res = handlers.handle_scrape({"url": "https://example.com/"})
    assert res["success"] is True
    assert res["warning"] == "truncated"
    assert res["data"]["markdown"] == "部分内容"


def test_scrape_timeout_is_milliseconds():
    """timeout=15000 必须按 15 秒预算解释，不是 15000 秒。"""
    with patch(
        "adapter.handlers.scrape_url_result",
        return_value=_scrape_result("ok", markdown="x"),
    ) as mock_scrape:
        res = handlers.handle_scrape({"url": "https://example.com/", "timeout": 15000})
    assert res["success"] is True
    assert mock_scrape.call_args[1]["timeout_s"] == 15.0


def test_scrape_wait_for_passed_through():
    with patch(
        "adapter.handlers.scrape_url_result",
        return_value=_scrape_result("ok", markdown="x"),
    ) as mock_scrape:
        handlers.handle_scrape({"url": "https://example.com/", "waitFor": 3000})
    assert mock_scrape.call_args[1]["wait_ms"] == 3000


def test_scrape_invalid_timeout_rejected():
    for bad in (-1, 0, "15000", True):
        res = handlers.handle_scrape({"url": "https://example.com/", "timeout": bad})
        assert res["success"] is False
        assert "timeout" in res["error"]


def test_extract_marks_failed_urls():
    from adapter.fetcher import ScrapeResult

    def fake_scrape(url, **kwargs):
        if "bad" in url:
            return ScrapeResult(url=url, final_url=url, status="not_found", detail="HTTP 404")
        return ScrapeResult(
            url=url, final_url=url, status="ok",
            document={"markdown": "ok", "metadata": {}},
        )

    with patch("adapter.handlers.scrape_url_result", side_effect=fake_scrape):
        res = handlers.handle_extract({"urls": ["https://good.example.com", "https://bad.example.com"]})
    assert res["success"] is True
    assert res["failedUrls"] == ["https://bad.example.com"]
    assert len(res["data"]) == 2


def test_start_crawl_missing_url():
    res = handlers.handle_start_crawl({})
    assert res["success"] is False
    assert res["code"] == "invalid_crawl_request"
    assert "Missing url" in res["error"]


def test_parse_crawl_request_defaults_and_boundaries():
    request = handlers.parse_crawl_request({"url": "https://example.com"})
    assert request.limit == config.crawl_default_limit
    assert request.max_depth == config.crawl_default_depth

    request = handlers.parse_crawl_request({
        "url": "https://example.com",
        "limit": config.max_crawl_limit,
        "maxDiscoveryDepth": 0,
    })
    assert request.limit == config.max_crawl_limit
    assert request.max_depth == 0


def test_parse_crawl_request_compiles_path_filters():
    request = handlers.parse_crawl_request({
        "url": "https://example.com",
        "includePaths": ["/docs/*", "/a.b+[]("],
        "excludePaths": ["/private"],
    })
    assert len(request.include_paths) == 2
    assert request.include_paths[0].regex is not None
    assert request.include_paths[1].source == "/a.b+[]("


def test_parse_crawl_request_rejects_invalid_numeric_values():
    for value in (True, "10", 1.5, None):
        res = handlers.handle_start_crawl({"url": "https://example.com", "limit": value})
        assert res["success"] is False
        assert res["code"] == "invalid_crawl_request"

    res = handlers.handle_start_crawl({
        "url": "https://example.com",
        "maxDiscoveryDepth": config.max_crawl_depth + 1,
    })
    assert res["success"] is False
    assert res["code"] == "invalid_crawl_request"


def test_parse_crawl_request_rejects_invalid_path_filters():
    invalid = (
        None,
        "/docs",
        [1],
        ["relative"],
        ["/x"] * (config.max_crawl_path_filters + 1),
        ["/" + "x" * config.max_crawl_path_length],
    )
    for value in invalid:
        res = handlers.handle_start_crawl({
            "url": "https://example.com",
            "includePaths": value,
        })
        assert res["success"] is False
        assert res["code"] == "invalid_crawl_request"


def test_start_crawl_capacity_error_is_identifiable():
    started = threading.Event()
    release = threading.Event()
    settings = dataclasses.replace(config, max_active_crawls=1, max_queued_crawls=0)

    def scrape(url, **kwargs):
        started.set()
        assert release.wait(2)
        return {"markdown": "ok", "links": []}

    dispatcher = reset_crawl_dispatcher_for_tests(settings=settings, scrape=scrape)
    first = handlers.handle_start_crawl({"url": "https://example.com", "limit": 1})
    assert first["success"] is True
    assert started.wait(1)
    second = handlers.handle_start_crawl({"url": "https://example.com/two", "limit": 1})
    assert second == {
        "success": False,
        "code": "crawl_capacity_exhausted",
        "error": "Crawl capacity exhausted",
    }
    release.set()
    dispatcher.shutdown(wait=True)
    reset_crawl_dispatcher_for_tests()


def test_crawl_status_exposes_progress_and_terminal_expiry():
    dispatcher = CrawlDispatcher(settings=config, scrape=lambda url, **kwargs: {
        "markdown": "ok",
        "links": [],
    })
    job_id = dispatcher.submit(handlers.parse_crawl_request({
        "url": "https://example.com",
        "limit": 1,
    }))
    import time

    deadline = time.monotonic() + 1
    while dispatcher.snapshot(job_id).status != "completed" and time.monotonic() < deadline:
        time.sleep(0.005)
    with patch("adapter.handlers.get_job", side_effect=dispatcher.snapshot):
        res = handlers.handle_crawl_status(job_id)
    assert res["status"] == "completed"
    assert res["completed"] == 1
    assert res["total"] == res["discovered"] == 1
    assert res["queued"] == 0
    assert res["failed"] == 0
    assert res["skipped"] == 0
    assert res["expiresAt"].endswith("Z")
    dispatcher.shutdown(wait=True)


def test_crawl_status_unknown_job():
    res = handlers.handle_crawl_status("nonexistent")
    assert res["success"] is False
    assert "Job not found" in res["error"]


def test_cancel_crawl_unknown_job():
    res = handlers.handle_cancel_crawl("nonexistent")
    assert res["success"] is False
    assert "Job not found" in res["error"]


def test_extract_missing_urls():
    res = handlers.handle_extract({})
    assert res["success"] is False
    assert "Missing urls" in res["error"]


def test_map_missing_url():
    res = handlers.handle_map({})
    assert res["success"] is False
    assert "Missing url" in res["error"]
