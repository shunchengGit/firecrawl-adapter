"""Tests for handler-level validation logic (no network calls)."""
from __future__ import annotations

from adapter import handlers


def test_search_missing_query():
    res = handlers.handle_search({})
    assert res["success"] is False
    assert "Missing query" in res["error"]


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
