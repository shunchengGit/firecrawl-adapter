"""Integration tests for HTTP routing against a live local server."""
from __future__ import annotations

import socket
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import httpx
import pytest

from adapter.server import Adapter, main  # noqa: F401


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _running_server(port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), Adapter)
    server.daemon_threads = True
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


@pytest.fixture
def base_url():
    port = _free_port()
    with _running_server(port) as url:
        yield url


def test_health_endpoint(base_url):
    resp = httpx.get(f"{base_url}/healthz", timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "searxng" in body
    # 测试环境 SearXNG 可能没跑，status 为 ok 或 degraded
    assert body["status"] in ("ok", "degraded")
    assert body["searxng"] in ("up", "down")


def test_health_alias(base_url):
    resp = httpx.get(f"{base_url}/health", timeout=5)
    assert resp.status_code == 200


def test_unknown_post_returns_404(base_url):
    resp = httpx.post(f"{base_url}/v2/unknown", json={}, timeout=5)
    assert resp.status_code == 404


def test_unknown_get_returns_404(base_url):
    resp = httpx.get(f"{base_url}/v2/unknown", timeout=5)
    assert resp.status_code == 404


def test_search_missing_query(base_url):
    resp = httpx.post(f"{base_url}/v2/search", json={}, timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "Missing query" in body["error"]


def test_scrape_missing_url(base_url):
    resp = httpx.post(f"{base_url}/v2/scrape", json={}, timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


def test_invalid_json_returns_400(base_url):
    resp = httpx.post(
        f"{base_url}/v2/search",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "Invalid JSON" in body["error"]


def test_crawl_status_unknown_job(base_url):
    resp = httpx.get(f"{base_url}/v2/crawl/nonexistent", timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
