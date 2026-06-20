"""Centralized configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from project root (two levels up from this file)
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass


@dataclass(frozen=True)
class Config:
    searxng_base: str
    listen_host: str
    listen_port: int
    user_agent: str
    max_scrape: int
    max_crawl_page_size: int
    max_jobs: int
    job_ttl_seconds: int
    max_body_bytes: int
    max_search_results: int
    crawl_timeout: int

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            searxng_base=os.getenv("SEARXNG_BASE", "http://127.0.0.1:3671"),
            listen_host=os.getenv("ADAPTER_HOST", "127.0.0.1"),
            listen_port=int(os.getenv("ADAPTER_PORT", "3672")),
            user_agent=os.getenv("ADAPTER_USER_AGENT", "hermes-searxng-adapter/3.0"),
            max_scrape=int(os.getenv("ADAPTER_MAX_SCRAPE", "60000")),
            max_crawl_page_size=int(os.getenv("ADAPTER_MAX_CRAWL_PAGE_SIZE", "24")),
            max_jobs=int(os.getenv("ADAPTER_MAX_JOBS", "100")),
            job_ttl_seconds=int(os.getenv("ADAPTER_JOB_TTL", "3600")),
            max_body_bytes=int(os.getenv("ADAPTER_MAX_BODY_BYTES", str(2 * 1024 * 1024))),
            max_search_results=int(os.getenv("ADAPTER_MAX_SEARCH_RESULTS", "20")),
            crawl_timeout=int(os.getenv("ADAPTER_CRAWL_TIMEOUT", "300")),
        )


config = Config.from_env()
