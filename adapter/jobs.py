"""Bounded asynchronous crawl jobs and lifecycle management."""
from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from .config import Config, config
from .fetcher import scrape_url
from .parser import CompiledPathPattern, match_path

_log = logging.getLogger("adapter")

CrawlStatus = Literal["queued", "scraping", "completed", "failed", "cancelled", "timeout"]
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timeout"})
_ACTIVE_STATUSES = frozenset({"queued", "scraping"})


@dataclass(frozen=True)
class CrawlRequest:
    url: str
    limit: int
    max_depth: int
    include_paths: tuple[CompiledPathPattern, ...] = ()
    exclude_paths: tuple[CompiledPathPattern, ...] = ()


@dataclass
class _CrawlJob:
    id: str
    request: CrawlRequest
    status: CrawlStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    discovered: int = 1
    queued: int = 1
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    data: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class CrawlJobSnapshot:
    id: str
    url: str
    status: CrawlStatus
    created_at: float
    started_at: float | None
    finished_at: float | None
    discovered: int
    queued: int
    completed: int
    failed: int
    skipped: int
    data: tuple[dict, ...]
    error: str | None

    @property
    def total(self) -> int:
        return self.discovered


class CrawlCapacityError(RuntimeError):
    code = "crawl_capacity_exhausted"


class CrawlDispatcherStoppedError(RuntimeError):
    code = "crawl_dispatcher_stopped"


class CrawlJobStore:
    def __init__(self, settings: Config = config) -> None:
        self._settings = settings
        self._jobs: dict[str, _CrawlJob] = {}
        self._lock = threading.Lock()

    def create_queued(self, request: CrawlRequest) -> CrawlJobSnapshot:
        self.cleanup()
        with self._lock:
            while True:
                job_id = uuid.uuid4().hex
                if job_id not in self._jobs:
                    break
            job = _CrawlJob(id=job_id, request=request)
            self._jobs[job_id] = job
            return self._snapshot_locked(job)

    def mark_scraping(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return False
            job.status = "scraping"
            job.started_at = time.time()
            return True

    def is_scraping(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.status == "scraping")

    def claim_page(self, job_id: str) -> bool:
        """Reserve the next frontier page; success is the fetch linearization point."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping" or job.queued <= 0:
                return False
            job.queued -= 1
            return True

    def record_page_success(
        self,
        job_id: str,
        document: dict,
        *,
        discovered: int = 0,
        enqueued: int = 0,
        skipped: int = 0,
    ) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping":
                return False
            job.data.append(copy.deepcopy(document))
            job.completed += 1
            job.discovered += discovered
            job.queued += enqueued
            job.skipped += skipped
            return True

    def record_page_failure(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping":
                return False
            job.failed += 1
            return True

    def record_page_skipped(self, job_id: str, count: int = 1) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping":
                return False
            job.skipped += count
            return True

    def discard_queued_pages(self, job_id: str, count: int) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping":
                return False
            discarded = min(max(count, 0), job.queued)
            job.queued -= discarded
            job.skipped += discarded
            return True

    def finish_completed(self, job_id: str) -> bool:
        return self._finish(job_id, "completed")

    def finish_failed(self, job_id: str, error: str = "crawl worker failed") -> bool:
        return self._finish(job_id, "failed", error)

    def finish_timeout(self, job_id: str) -> bool:
        return self._finish(job_id, "timeout")

    def _finish(self, job_id: str, status: CrawlStatus, error: str | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "scraping":
                return False
            job.skipped += job.queued
            job.queued = 0
            job.status = status
            job.finished_at = time.time()
            job.error = error
            return True

    def cancel(self, job_id: str) -> CrawlJobSnapshot | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status in _ACTIVE_STATUSES:
                job.skipped += job.queued
                job.queued = 0
                job.status = "cancelled"
                job.finished_at = time.time()
            return self._snapshot_locked(job)

    def cancel_all_unfinished(self) -> int:
        with self._lock:
            now = time.time()
            count = 0
            for job in self._jobs.values():
                if job.status in _ACTIVE_STATUSES:
                    job.skipped += job.queued
                    job.queued = 0
                    job.status = "cancelled"
                    job.finished_at = now
                    count += 1
            return count

    def snapshot(self, job_id: str) -> CrawlJobSnapshot | None:
        self.cleanup()
        with self._lock:
            job = self._jobs.get(job_id)
            return self._snapshot_locked(job) if job else None

    def cleanup(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in _TERMINAL_STATUSES
                and job.finished_at is not None
                and now - job.finished_at >= self._settings.job_ttl_seconds
            ]
            for job_id in expired:
                del self._jobs[job_id]
                removed += 1

            terminal = sorted(
                (job for job in self._jobs.values() if job.status in _TERMINAL_STATUSES),
                key=lambda job: (job.finished_at or job.created_at, job.id),
            )
            excess = len(terminal) - self._settings.max_jobs
            for job in terminal[: max(excess, 0)]:
                del self._jobs[job.id]
                removed += 1
        return removed

    def count(self) -> int:
        with self._lock:
            return len(self._jobs)

    @staticmethod
    def _snapshot_locked(job: _CrawlJob) -> CrawlJobSnapshot:
        return CrawlJobSnapshot(
            id=job.id,
            url=job.request.url,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            discovered=job.discovered,
            queued=job.queued,
            completed=job.completed,
            failed=job.failed,
            skipped=job.skipped,
            data=tuple(copy.deepcopy(job.data)),
            error=job.error,
        )


ScrapeCallable = Callable[..., dict]


def _is_fetch_failure(document: dict) -> bool:
    markdown = document.get("markdown")
    return isinstance(markdown, str) and markdown.startswith("[fetch failed:")


def crawl_worker(
    job_id: str,
    request: CrawlRequest,
    store: CrawlJobStore,
    *,
    scrape: ScrapeCallable = scrape_url,
) -> None:
    """Run one sequential, same-host BFS crawl and publish progress incrementally."""
    queue: deque[tuple[str, int]] = deque([(request.url, 0)])
    seen = {request.url}
    origin = urlparse(request.url).netloc.lower()
    max_frontier = request.limit * 5
    attempts = 0

    while queue and attempts < request.limit:
        if not store.is_scraping(job_id):
            return
        current, depth = queue.popleft()
        if not store.claim_page(job_id):
            return

        if request.exclude_paths and match_path(current, request.exclude_paths):
            store.record_page_skipped(job_id)
            continue
        if request.include_paths and not match_path(current, request.include_paths):
            store.record_page_skipped(job_id)
            continue

        try:
            document = scrape(current, formats=["markdown"], timeout=10)
        except Exception as exc:
            _log.warning("Crawl page failed for %s: %s", current, exc)
            if store.record_page_failure(job_id):
                attempts += 1
            continue

        if not store.is_scraping(job_id):
            return
        if _is_fetch_failure(document):
            if store.record_page_failure(job_id):
                attempts += 1
            continue

        discovered = 0
        enqueued = 0
        skipped = 0
        if depth < request.max_depth:
            for link in document.get("links", []):
                if not isinstance(link, str) or link in seen:
                    continue
                if urlparse(link).netloc.lower() != origin:
                    continue
                if request.exclude_paths and match_path(link, request.exclude_paths):
                    continue
                if request.include_paths and not match_path(link, request.include_paths):
                    continue
                seen.add(link)
                discovered += 1
                if len(queue) < max_frontier:
                    queue.append((link, depth + 1))
                    enqueued += 1
                else:
                    skipped += 1

        if not store.record_page_success(
            job_id,
            document,
            discovered=discovered,
            enqueued=enqueued,
            skipped=skipped,
        ):
            return
        attempts += 1

    if queue:
        store.discard_queued_pages(job_id, len(queue))
    store.finish_completed(job_id)


class CrawlDispatcher:
    def __init__(
        self,
        *,
        settings: Config = config,
        store: CrawlJobStore | None = None,
        scrape: ScrapeCallable = scrape_url,
    ) -> None:
        self.settings = settings
        self.store = store or CrawlJobStore(settings)
        self._scrape = scrape
        self._executor: ThreadPoolExecutor | None = None
        self._pending: deque[tuple[str, CrawlRequest]] = deque()
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.RLock()
        self._accepting = True

    def submit(self, request: CrawlRequest) -> str:
        with self._lock:
            if not self._accepting:
                raise CrawlDispatcherStoppedError("Crawl dispatcher is stopped")
            self.store.cleanup()
            self._remove_done_futures_locked()
            if (
                len(self._futures) >= self.settings.max_active_crawls
                and len(self._pending) >= self.settings.max_queued_crawls
            ):
                raise CrawlCapacityError("Crawl capacity exhausted")

            snapshot = self.store.create_queued(request)
            if len(self._futures) < self.settings.max_active_crawls:
                self._start_locked(snapshot.id, request)
            else:
                self._pending.append((snapshot.id, request))
            return snapshot.id

    def cancel(self, job_id: str) -> CrawlJobSnapshot | None:
        with self._lock:
            snapshot = self.store.cancel(job_id)
            if not snapshot:
                return None
            if snapshot.status == "cancelled":
                self._pending = deque(item for item in self._pending if item[0] != job_id)
                future = self._futures.get(job_id)
                if future:
                    future.cancel()
                self._drain_locked()
            return snapshot

    def snapshot(self, job_id: str) -> CrawlJobSnapshot | None:
        return self.store.snapshot(job_id)

    def shutdown(self, *, wait: bool = False) -> int:
        with self._lock:
            self._accepting = False
            cancelled = self.store.cancel_all_unfinished()
            self._pending.clear()
            for future in self._futures.values():
                future.cancel()
            executor = self._executor
            self._executor = None
        if executor:
            executor.shutdown(wait=wait, cancel_futures=True)
        return cancelled

    def _executor_locked(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.settings.max_active_crawls,
                thread_name_prefix="crawl",
            )
        return self._executor

    def _start_locked(self, job_id: str, request: CrawlRequest) -> None:
        future = self._executor_locked().submit(self._run, job_id, request)
        self._futures[job_id] = future
        future.add_done_callback(self._done_callback(job_id))

    def _done_callback(self, job_id: str) -> Callable[[Future[None]], None]:
        def callback(completed: Future[None]) -> None:
            self._future_done(job_id, completed)

        return callback

    def _run(self, job_id: str, request: CrawlRequest) -> None:
        if not self.store.mark_scraping(job_id):
            return
        timer = threading.Timer(self.settings.crawl_timeout, self.store.finish_timeout, (job_id,))
        timer.daemon = True
        timer.start()
        try:
            crawl_worker(job_id, request, self.store, scrape=self._scrape)
        except Exception:
            _log.exception("Crawl worker failed for job %s", job_id)
            self.store.finish_failed(job_id, "crawl worker failed")
        finally:
            timer.cancel()

    def _future_done(self, job_id: str, future: Future[None]) -> None:
        if not future.cancelled():
            try:
                future.result()
            except Exception:
                _log.exception("Crawl future failed for job %s", job_id)
                self.store.finish_failed(job_id, "crawl dispatcher failed")
        with self._lock:
            self._futures.pop(job_id, None)
            self._drain_locked()

    def _remove_done_futures_locked(self) -> None:
        for job_id, future in list(self._futures.items()):
            if future.done():
                self._futures.pop(job_id, None)

    def _drain_locked(self) -> None:
        if not self._accepting:
            return
        self._remove_done_futures_locked()
        while self._pending and len(self._futures) < self.settings.max_active_crawls:
            job_id, request = self._pending.popleft()
            snapshot = self.store.snapshot(job_id)
            if snapshot and snapshot.status == "queued":
                self._start_locked(job_id, request)


_dispatcher_lock = threading.Lock()
_dispatcher: CrawlDispatcher | None = None


def _get_dispatcher() -> CrawlDispatcher:
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            _dispatcher = CrawlDispatcher()
        return _dispatcher


def submit_crawl(request: CrawlRequest) -> str:
    return _get_dispatcher().submit(request)


def get_job(job_id: str) -> CrawlJobSnapshot | None:
    return _get_dispatcher().snapshot(job_id)


def cancel_job(job_id: str) -> CrawlJobSnapshot | None:
    return _get_dispatcher().cancel(job_id)


def shutdown_crawl_dispatcher(*, wait: bool = False) -> int:
    return _get_dispatcher().shutdown(wait=wait)


def reset_crawl_dispatcher_for_tests(
    *,
    settings: Config = config,
    scrape: ScrapeCallable = scrape_url,
) -> CrawlDispatcher:
    global _dispatcher
    with _dispatcher_lock:
        previous = _dispatcher
        _dispatcher = CrawlDispatcher(settings=settings, scrape=scrape)
    if previous:
        previous.shutdown(wait=True)
    return _dispatcher
