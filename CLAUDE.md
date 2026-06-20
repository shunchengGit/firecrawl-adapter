# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, free drop-in replacement for the Firecrawl API. Hermes (an external agent) points `FIRECRAWL_API_URL` at this adapter; the adapter translates Firecrawl's `/v2/*` protocol into SearXNG searches + direct page scraping. No paid API keys.

```
Hermes → adapter (port 3672) → SearXNG (port 3671) → Google/Bing/Baidu/...
```

## Common commands

```bash
# Run adapter locally (needs SearXNG running first)
docker compose up -d            # start SearXNG + Redis only
python -m adapter               # start adapter on :3672

# Tests / lint / types
pytest                          # all tests
pytest tests/test_parser.py::test_match_path_wildcard   # single test
ruff check adapter/ tests/      # lint (auto-fix: --fix)
mypy adapter/                   # type check (must be 0 errors)

# Rebuild Docker adapter image (optional, full-Docker mode)
docker compose up -d --build
```

System Python is 3.9 but `pyproject.toml` targets 3.10+. The package uses `from __future__ import annotations`, so it imports on 3.9, but dev tooling (ruff/mypy) assumes 3.10+. Install dev deps with `pip install -e ".[dev]"`.

## Architecture

The `adapter/` package is split by concern — HTTP layer is thin, business logic lives in pure functions that return dicts:

- **`server.py`** — `ThreadingHTTPServer` + `BaseHTTPRequestHandler` subclass. Only does routing + JSON I/O + error wrapping. Delegates every endpoint to a `handlers.*` function. This is the only place that touches sockets.
- **`handlers.py`** — One function per endpoint (`handle_search`, `handle_scrape`, `handle_start_crawl`, `handle_crawl_status`, `handle_cancel_crawl`, `handle_extract`, `handle_map`). Each takes a parsed `body` dict, returns a response dict. No HTTP awareness — this is what makes them unit-testable.
- **`fetcher.py`** — All network I/O. `scrape_url()` tries `requests.get` first; if the page looks bot-blocked (heuristic: <500 chars visible text, or WAF keywords), it falls back to `scrape_url_headless()` which shells out to `agent-browser`. Also has `searxng_search()` and `map_url()`.
- **`jobs.py`** — In-memory crawl job store (`_jobs` dict + lock). `crawl_worker()` runs in a daemon thread, BFS through same-domain links up to `max_depth`. `cleanup_old_jobs()` enforces TTL + max count — called on every new job to prevent unbounded memory growth.
- **`parser.py`** — Pure HTML helpers: `extract_main()`, `get_meta()`, `match_path()`, `html_to_markdown()`. Thread-local `HTML2Text` instance (the library isn't thread-safe).
- **`config.py`** — Frozen `Config` dataclass, all values from env vars with defaults. Single `config` instance imported everywhere.

**Key flow for `/v2/scrape`:** `server.do_POST` → `handlers.handle_scrape` (retries 3x) → `fetcher.scrape_url` → requests.get → on failure → `scrape_url_headless` (subprocess to `agent-browser`) → `parser` to build markdown/metadata/links.

**Crawl is async:** `POST /v2/crawl` returns a job_id immediately, spawns `_crawl_worker` thread, client polls `GET /v2/crawl/:id`. Pagination via virtual `?page=N` query param (real Firecrawl uses opaque `next` URLs — this is a simplification).

## Things that bit us / non-obvious

- **agent-browser subprocess calls are expensive** — `open` + `get url` + `eval` + `close` = 4 process launches per scrape. The `finally: close` in `scrape_url_headless` shuts down the whole daemon every time, so next scrape cold-starts Chrome. If performance matters, consider letting the daemon persist.
- **agent-browser session persistence**: `~/.agent-browser/config.json` does NOT support a `session_name` field (only plugins). To default a session name, set `AGENT_BROWSER_SESSION_NAME` env var (it's in `~/.zshrc` as `firecrawl-adapter`). State auto-saves to `~/.agent-browser/sessions/<name>-default.json` on `close --all`.
- **Docker image has no agent-browser** — the Dockerfile is Python-only. Headless fallback only works in local-run mode. Don't try to add agent-browser to the image; Chromium install + Chrome-for-Testing download fails due to network restrictions in build.
- **`_is_likely_blocked` threshold (500 chars)** misfires on legitimately short pages (e.g. `example.com`). This is intentional to catch Cloudflare challenge pages, but expect false positives on minimal content.
- **SearXNG config is mounted read-only** via `docker-compose.yml` — edit `searxng/settings.yml` locally, restart container to apply.

## SearXNG

Runs in Docker (`docker compose up -d`). Config at `searxng/settings.yml` (engines: Google, Bing, DuckDuckGo, Wikipedia, Wikidata, Baidu, Sogou). `secret_key` is hardcoded `"hermes-searxng-local"` — fine for local-only but don't expose. Port 3671 on host → 8080 in container.
