"""Tests for handler-level validation logic (no network calls)."""
from __future__ import annotations

from unittest.mock import patch

from adapter import handlers


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


def test_start_crawl_missing_url():
    res = handlers.handle_start_crawl({})
    assert res["success"] is False
    assert "Missing url" in res["error"]


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
