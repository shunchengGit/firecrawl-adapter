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
    """limit is capped to config.max_search_results."""
    with patch("adapter.handlers.searxng_search") as mock_search:
        mock_search.return_value = []
        handlers.handle_search({"query": "test", "limit": 9999})
        # The limit passed to searxng_search should be capped
        from adapter.config import config
        assert mock_search.call_args[1]["limit"] <= config.max_search_results


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


def test_search_domain_filtering():
    """Domain post-filtering: includeDomains / excludeDomains."""
    raw_results = [
        {"title": "A", "url": "https://docs.example.com/a", "content": "..."},
        {"title": "B", "url": "https://blog.example.com/b", "content": "..."},
        {"title": "C", "url": "https://other.com/c", "content": "..."},
    ]
    with patch("adapter.handlers.searxng_search", return_value=raw_results):
        res = handlers.handle_search({
            "query": "test",
            "includeDomains": ["docs.example.com"],
        })
    urls = [r["url"] for r in res["data"]["web"]]
    assert urls == ["https://docs.example.com/a"]

    with patch("adapter.handlers.searxng_search", return_value=raw_results):
        res = handlers.handle_search({
            "query": "test",
            "excludeDomains": ["other.com"],
        })
    urls = [r["url"] for r in res["data"]["web"]]
    assert len(urls) == 2
    assert "https://other.com/c" not in urls


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
