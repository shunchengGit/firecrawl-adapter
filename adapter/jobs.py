"""Async crawl job storage and worker."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from urllib.parse import urlparse

from .config import config
from .fetcher import scrape_url
from .parser import match_path

_log = logging.getLogger("adapter")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def cleanup_old_jobs() -> None:
    """Remove expired jobs to prevent memory leak."""
    now = time.time()
    with _jobs_lock:
        expired = [
            jid
            for jid, job in _jobs.items()
            if now - job.get("created_at", now) > config.job_ttl_seconds
        ]
        for jid in expired:
            del _jobs[jid]
        if len(_jobs) > config.max_jobs:
            sorted_jobs = sorted(_jobs.items(), key=lambda x: x[1].get("created_at", 0))
            for jid, _ in sorted_jobs[: len(_jobs) - config.max_jobs]:
                del _jobs[jid]


def create_job(url: str) -> str:
    cleanup_old_jobs()
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "url": url,
            "status": "scraping",
            "completed": 0,
            "total": 0,
            "data": [],
            "next": None,
            "created_at": time.time(),
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return job.copy() if job else None


def cancel_job(job_id: str) -> bool:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j:
            j["status"] = "cancelled"
            return True
        return False


def crawl_worker(
    job_id: str,
    url: str,
    limit: int = 10,
    max_depth: int = 1,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> None:
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(url, 0)])
    docs: list[dict] = []

    while queue and len(docs) < limit:
        cur, depth = queue.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        if exclude_paths and match_path(cur, exclude_paths):
            continue
        if include_paths and not match_path(cur, include_paths):
            continue
        try:
            doc = scrape_url(cur, formats=["markdown"], timeout=10)
            docs.append(doc)
            if depth < max_depth:
                base = urlparse(cur).netloc
                for lnk in doc.get("links", []):
                    if (
                        len(queue) < limit * 5
                        and urlparse(lnk).netloc == base
                        and lnk not in seen
                    ):
                        queue.append((lnk, depth + 1))
        except Exception as e:
            _log.warning("Crawl worker error for %s: %s", cur, e)
            continue

    with _jobs_lock:
        j = _jobs.get(job_id)
        if j and j["status"] not in ("cancelled",):
            j["status"] = "completed"
            j["completed"] = len(docs)
            j["total"] = len(docs)
            j["data"] = docs
