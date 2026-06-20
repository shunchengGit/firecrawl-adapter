"""HTTP server and request routing."""
from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import signal
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import handlers
from .config import config
from .fetcher import check_searxng
from .jobs import mark_all_running_cancelled

logging.basicConfig(level=logging.WARNING, format="[adapter] %(message)s")
_log = logging.getLogger("adapter")

_CRAWL_RE = re.compile(r"/v[12]/crawl/([^/?]+)")


class Adapter(BaseHTTPRequestHandler):
    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n == 0:
            return {}
        if n > config.max_body_bytes:
            raise ValueError(
                f"Request body too large: {n} bytes (max {config.max_body_bytes})"
            )
        raw = self.rfile.read(n)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

    def _json(self, code: int, data: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        try:
            body = self._body()
            if path in ("/v1/search", "/v2/search"):
                res = handlers.handle_search(body)
            elif path in ("/v1/scrape", "/v2/scrape"):
                res = handlers.handle_scrape(body)
            elif path in ("/v1/crawl", "/v2/crawl"):
                res = handlers.handle_start_crawl(body)
            elif path == "/v2/extract":
                res = handlers.handle_extract(body)
            elif path in ("/v1/map", "/v2/map"):
                res = handlers.handle_map(body)
            else:
                self.send_error(404)
                return
            self._json(200, res)
        except ValueError as e:
            self._json(400, {"success": False, "error": str(e)})
        except Exception as e:
            _log.exception("POST %s failed", path)
            self._json(500, {"success": False, "error": f"Internal adapter error: {e}"})

    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        try:
            if path in ("/healthz", "/health"):
                searxng_up = check_searxng()
                self._json(200, {
                    "status": "ok" if searxng_up else "degraded",
                    "searxng": "up" if searxng_up else "down",
                })
                return
            m = _CRAWL_RE.match(path)
            if m:
                qs = self.path.split("?")[-1] if "?" in self.path else ""
                query = dict(urllib.parse.parse_qsl(qs)) if qs else {}
                self._json(200, handlers.handle_crawl_status(m.group(1), query))
            else:
                self.send_error(404)
        except Exception as e:
            _log.exception("GET %s failed", path)
            self._json(500, {"success": False, "error": f"Internal adapter error: {e}"})

    def do_DELETE(self) -> None:
        path = self.path.rstrip("/")
        try:
            m = _CRAWL_RE.match(path)
            if m:
                self._json(200, handlers.handle_cancel_crawl(m.group(1)))
            else:
                self.send_error(404)
        except Exception as e:
            _log.exception("DELETE %s failed", path)
            self._json(500, {"success": False, "error": f"Internal adapter error: {e}"})

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    print(f"SearXNG Firecrawl adapter — http://{config.listen_host}:{config.listen_port}")
    print("  POST /v2/search | /v1/search")
    print("  POST /v2/scrape    (formats, onlyMainContent)")
    print("  POST /v2/crawl     (limit, maxDiscoveryDepth, includePaths, excludePaths)")
    print("  GET  /v2/crawl/:id (?page=N for pagination)")
    print("  DELETE /v2/crawl/:id")
    print("  POST /v2/map")
    print("  GET  /healthz")
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), Adapter)
    server.daemon_threads = True

    def _shutdown(signum, frame):
        _log.warning("收到信号 %s，优雅关闭中...", signum)
        n = mark_all_running_cancelled()
        if n:
            _log.warning("已标记 %d 个运行中 crawl 为 cancelled", n)
        # 关 agent-browser daemon，触发 session cookie 落盘
        agent_bin = shutil.which("agent-browser")
        if agent_bin:
            with contextlib.suppress(Exception):
                subprocess.run(
                    [agent_bin, "close", "--all"],
                    capture_output=True,
                    timeout=10,
                )
        # 在新线程里 shutdown，避免与主线程 serve_forever 死锁
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    server.serve_forever()
