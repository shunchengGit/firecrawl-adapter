"""Crawl job store, dispatcher, and worker tests."""
from __future__ import annotations

import dataclasses
import threading
import time
from unittest.mock import patch

from adapter.config import config
from adapter.jobs import (
    CrawlCapacityError,
    CrawlDispatcher,
    CrawlDispatcherStoppedError,
    CrawlJobStore,
    CrawlRequest,
)


def _settings(**changes):
    defaults = {
        "crawl_timeout": 2,
        "max_jobs": 10,
        "job_ttl_seconds": 60,
        "max_active_crawls": 1,
        "max_queued_crawls": 1,
    }
    defaults.update(changes)
    return dataclasses.replace(config, **defaults)


def _request(url: str = "https://example.com", **changes) -> CrawlRequest:
    return dataclasses.replace(CrawlRequest(url=url, limit=5, max_depth=1), **changes)


def _wait_for_status(dispatcher: CrawlDispatcher, job_id: str, status: str, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = dispatcher.snapshot(job_id)
        if snapshot and snapshot.status == status:
            return snapshot
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach {status}")


def test_terminal_transition_race_has_one_winner():
    store = CrawlJobStore(_settings())
    job = store.create_queued(_request())
    store.mark_scraping(job.id)
    barrier = threading.Barrier(3)
    results: list[bool | str] = []

    def complete():
        barrier.wait()
        results.append(store.finish_completed(job.id))

    def cancel():
        barrier.wait()
        snapshot = store.cancel(job.id)
        results.append(snapshot.status)

    threads = [threading.Thread(target=complete), threading.Thread(target=cancel)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    snapshot = store.snapshot(job.id)
    assert snapshot.status in ("completed", "cancelled")
    assert snapshot.finished_at is not None
    assert not store.finish_timeout(job.id)


def test_store_transitions_are_terminal_and_cancel_is_idempotent():
    store = CrawlJobStore(_settings())
    job = store.create_queued(_request())
    assert store.mark_scraping(job.id)
    assert store.record_page_success(job.id, {"markdown": "ok"})
    assert store.finish_completed(job.id)
    assert not store.finish_timeout(job.id)
    assert not store.finish_failed(job.id)
    assert store.cancel(job.id).status == "completed"

    cancelled = store.create_queued(_request("https://example.com/two"))
    assert store.cancel(cancelled.id).status == "cancelled"
    assert store.cancel(cancelled.id).status == "cancelled"
    assert not store.mark_scraping(cancelled.id)


def test_store_uses_full_uuid_and_retries_collision():
    store = CrawlJobStore(_settings())
    first_uuid = type("UUID", (), {"hex": "a" * 32})()
    second_uuid = type("UUID", (), {"hex": "b" * 32})()
    with patch("adapter.jobs.uuid.uuid4", side_effect=[first_uuid, first_uuid, second_uuid]):
        first = store.create_queued(_request())
        second = store.create_queued(_request("https://example.com/two"))
    assert first.id == "a" * 32
    assert second.id == "b" * 32
    assert len(first.id) == 32


def test_snapshot_is_deeply_detached():
    store = CrawlJobStore(_settings())
    job = store.create_queued(_request())
    store.mark_scraping(job.id)
    store.record_page_success(job.id, {"metadata": {"title": "original"}})
    snapshot = store.snapshot(job.id)
    snapshot.data[0]["metadata"]["title"] = "changed"
    assert store.snapshot(job.id).data[0]["metadata"]["title"] == "original"


def test_cleanup_only_removes_terminal_jobs():
    settings = _settings(job_ttl_seconds=1, max_jobs=1)
    store = CrawlJobStore(settings)
    active = store.create_queued(_request())
    store.mark_scraping(active.id)
    terminal = store.create_queued(_request("https://example.com/done"))
    store.mark_scraping(terminal.id)
    store.finish_completed(terminal.id)

    finished_at = store.snapshot(terminal.id).finished_at
    store.cleanup(now=finished_at + 2)
    assert store.snapshot(active.id) is not None
    assert store.snapshot(terminal.id) is None


def test_cleanup_evicts_oldest_terminal_history():
    settings = _settings(max_jobs=1)
    store = CrawlJobStore(settings)
    one = store.create_queued(_request("https://example.com/one"))
    store.mark_scraping(one.id)
    store.finish_completed(one.id)
    two = store.create_queued(_request("https://example.com/two"))
    store.mark_scraping(two.id)
    store.finish_completed(two.id)
    store.cleanup()
    assert store.snapshot(one.id) is None
    assert store.snapshot(two.id) is not None


def test_dispatcher_bounds_active_and_queued_jobs():
    started = threading.Event()
    release = threading.Event()
    fetched: list[str] = []

    def scrape(url, **kwargs):
        fetched.append(url)
        started.set()
        assert release.wait(2)
        return {"markdown": "ok", "links": []}

    dispatcher = CrawlDispatcher(settings=_settings(), scrape=scrape)
    first = dispatcher.submit(_request("https://example.com/one", limit=1))
    assert started.wait(1)
    second = dispatcher.submit(_request("https://example.com/two", limit=1))
    assert dispatcher.snapshot(second).status == "queued"
    try:
        dispatcher.submit(_request("https://example.com/three", limit=1))
    except CrawlCapacityError as exc:
        assert exc.code == "crawl_capacity_exhausted"
    else:
        raise AssertionError("third job should be rejected")

    cancelled = dispatcher.cancel(second)
    assert cancelled.status == "cancelled"
    assert cancelled.queued == 0
    assert cancelled.skipped == 1
    release.set()
    _wait_for_status(dispatcher, first, "completed")
    time.sleep(0.02)
    assert fetched == ["https://example.com/one"]
    dispatcher.shutdown(wait=True)


def test_submit_does_not_count_done_future_as_active():
    dispatcher = CrawlDispatcher(
        settings=_settings(max_queued_crawls=0),
        scrape=lambda url, **kwargs: {"markdown": "ok", "links": []},
    )
    first = dispatcher.submit(_request("https://example.com/one", limit=1))
    _wait_for_status(dispatcher, first, "completed")

    with dispatcher._lock:
        future = dispatcher._futures.get(first)
        if future is not None:
            assert future.done()
        second = dispatcher.submit(_request("https://example.com/two", limit=1))

    _wait_for_status(dispatcher, second, "completed")
    dispatcher.shutdown(wait=True)


def test_dispatcher_runs_queued_job_when_slot_is_released():
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()

    def scrape(url, **kwargs):
        if url.endswith("one"):
            first_started.set()
            assert first_release.wait(2)
        else:
            second_started.set()
        return {"markdown": "ok", "links": []}

    dispatcher = CrawlDispatcher(settings=_settings(), scrape=scrape)
    first = dispatcher.submit(_request("https://example.com/one", limit=1))
    assert first_started.wait(1)
    second = dispatcher.submit(_request("https://example.com/two", limit=1))
    first_release.set()
    _wait_for_status(dispatcher, first, "completed")
    assert second_started.wait(1)
    _wait_for_status(dispatcher, second, "completed")
    dispatcher.shutdown(wait=True)


def test_dispatcher_shutdown_cancels_and_rejects_work():
    started = threading.Event()
    release = threading.Event()

    def scrape(url, **kwargs):
        started.set()
        assert release.wait(2)
        return {"markdown": "ok", "links": []}

    dispatcher = CrawlDispatcher(settings=_settings(), scrape=scrape)
    first = dispatcher.submit(_request(limit=1))
    assert started.wait(1)
    second = dispatcher.submit(_request("https://example.com/two", limit=1))
    assert dispatcher.shutdown(wait=False) == 2
    first_snapshot = dispatcher.snapshot(first)
    second_snapshot = dispatcher.snapshot(second)
    assert first_snapshot.status == "cancelled"
    assert second_snapshot.status == "cancelled"
    assert first_snapshot.queued == 0
    assert second_snapshot.queued == 0
    try:
        dispatcher.submit(_request("https://example.com/three"))
    except CrawlDispatcherStoppedError:
        pass
    else:
        raise AssertionError("stopped dispatcher accepted work")
    release.set()


def test_worker_publishes_progress_and_continues_after_page_failure():
    second_started = threading.Event()
    release_second = threading.Event()

    def scrape(url, **kwargs):
        if url.endswith("/"):
            return {
                "markdown": "home",
                "links": [
                    "https://example.com/fail",
                    "https://example.com/second",
                    "https://outside.example/x",
                ],
            }
        if url.endswith("fail"):
            raise RuntimeError("expected page failure")
        second_started.set()
        assert release_second.wait(2)
        return {"markdown": "second", "links": []}

    dispatcher = CrawlDispatcher(settings=_settings(), scrape=scrape)
    job_id = dispatcher.submit(_request("https://example.com/", limit=3))
    assert second_started.wait(1)
    snapshot = dispatcher.snapshot(job_id)
    assert snapshot.status == "scraping"
    assert snapshot.completed == 1
    assert snapshot.failed == 1
    assert snapshot.discovered == 3
    assert snapshot.queued == 0
    assert len(snapshot.data) == 1
    release_second.set()
    final = _wait_for_status(dispatcher, job_id, "completed")
    assert final.completed == 2
    assert final.failed == 1
    assert len(final.data) == 2
    dispatcher.shutdown(wait=True)


def test_unexpected_worker_error_becomes_sanitized_failed_state():
    dispatcher = CrawlDispatcher(
        settings=_settings(),
        scrape=lambda url, **kwargs: {"markdown": "ok", "links": None},
    )
    job_id = dispatcher.submit(_request(limit=2))
    final = _wait_for_status(dispatcher, job_id, "failed")
    assert final.error == "crawl worker failed"
    assert "NoneType" not in final.error
    dispatcher.shutdown(wait=True)


def test_worker_treats_synthetic_fetch_failure_as_failure():
    dispatcher = CrawlDispatcher(
        settings=_settings(),
        scrape=lambda url, **kwargs: {"markdown": "[fetch failed: unavailable]", "links": []},
    )
    job_id = dispatcher.submit(_request(limit=1))
    final = _wait_for_status(dispatcher, job_id, "completed")
    assert final.completed == 0
    assert final.failed == 1
    assert final.data == ()
    dispatcher.shutdown(wait=True)


def test_timeout_freezes_progress_after_inflight_fetch():
    started = threading.Event()
    release = threading.Event()

    def scrape(url, **kwargs):
        started.set()
        assert release.wait(2)
        return {
            "markdown": "late",
            "links": ["https://example.com/never"],
        }

    dispatcher = CrawlDispatcher(settings=_settings(crawl_timeout=0.05), scrape=scrape)
    job_id = dispatcher.submit(_request(limit=2))
    assert started.wait(1)
    timed_out = _wait_for_status(dispatcher, job_id, "timeout")
    release.set()
    time.sleep(0.05)
    frozen = dispatcher.snapshot(job_id)
    assert frozen.status == "timeout"
    assert frozen.completed == timed_out.completed == 0
    assert frozen.data == ()
    dispatcher.shutdown(wait=True)


def test_cancel_during_fetch_prevents_result_and_more_scheduling():
    started = threading.Event()
    release = threading.Event()
    fetched: list[str] = []

    def scrape(url, **kwargs):
        fetched.append(url)
        started.set()
        assert release.wait(2)
        return {"markdown": "late", "links": ["https://example.com/next"]}

    dispatcher = CrawlDispatcher(settings=_settings(), scrape=scrape)
    job_id = dispatcher.submit(_request(limit=2))
    assert started.wait(1)
    assert dispatcher.cancel(job_id).status == "cancelled"
    release.set()
    time.sleep(0.05)
    final = dispatcher.snapshot(job_id)
    assert final.status == "cancelled"
    assert final.completed == 0
    assert fetched == ["https://example.com"]
    dispatcher.shutdown(wait=True)
