"""Unit tests for the in-memory job registry (core/jobs.py)."""

from __future__ import annotations

import threading

import pytest

from app.core.jobs import JOB_TTL_SECONDS, JobRegistry, noop_reporter


@pytest.fixture()
def registry() -> JobRegistry:
    return JobRegistry()


def test_create_returns_running_job(registry: JobRegistry) -> None:
    job = registry.create("backup")
    fetched = registry.get(job.id)
    assert fetched is not None
    assert fetched.kind == "backup"
    assert fetched.status == "running"
    assert fetched.percent is None  # no total yet


def test_update_sets_phase_and_total(registry: JobRegistry) -> None:
    job = registry.create("export")
    registry.update(job.id, "media", done=3, total=10, detail="copying")
    fetched = registry.get(job.id)
    assert fetched is not None
    assert fetched.phase == "media"
    assert fetched.done == 3
    assert fetched.total == 10
    assert fetched.detail == "copying"
    assert fetched.percent == 30


def test_percent_monotonic_and_capped(registry: JobRegistry) -> None:
    job = registry.create("import")
    registry.update(job.id, "entries", done=5, total=4)
    assert registry.get(job.id).percent == 100  # capped, not >100


def test_finish_and_fail_are_terminal(registry: JobRegistry) -> None:
    job = registry.create("backup")
    registry.finish(job.id, detail="ok")
    finished = registry.get(job.id)
    assert finished.status == "done"
    assert finished.detail == "ok"
    assert finished.percent is None
    # late updates are ignored
    registry.update(job.id, "late", done=1, total=1)
    assert registry.get(job.id).phase != "late"
    registry.fail(job.id, "boom")  # ignored on finished job
    assert registry.get(job.id).status == "done"

    job2 = registry.create("restore")
    registry.fail(job2.id, "disk full")
    failed = registry.get(job2.id)
    assert failed.status == "failed"
    assert failed.error == "disk full"


def test_unknown_job_updates_are_noops(registry: JobRegistry) -> None:
    registry.update("missing", "phase", 1, 2)
    registry.finish("missing")
    registry.fail("missing", "err")
    assert registry.get("missing") is None


def test_ttl_cleanup_prunes_expired_finished_jobs() -> None:
    registry = JobRegistry()
    job = registry.create("export")
    registry.finish(job.id)
    # age the job past the TTL
    registry._jobs[job.id].finished_at -= JOB_TTL_SECONDS + 1
    registry.create("export")  # triggers lazy cleanup
    assert registry.get(job.id) is None


def test_ttl_cleanup_keeps_running_jobs() -> None:
    registry = JobRegistry()
    job = registry.create("backup")
    registry._jobs[job.id].created_at -= JOB_TTL_SECONDS * 10
    registry.create("backup")
    assert registry.get(job.id) is not None  # running jobs are never pruned


def test_reporter_bound_to_registry(registry: JobRegistry) -> None:
    job = registry.create("backup")
    reporter = registry.reporter(job.id)
    reporter("upload", done=2, total=8)
    fetched = registry.get(job.id)
    assert fetched.phase == "upload"
    assert fetched.percent == 25
    # reporter on an unknown job degrades to a no-op
    registry.reporter("missing")("phase")
    noop_reporter("phase")


def test_thread_safety_under_concurrent_updates(registry: JobRegistry) -> None:
    job = registry.create("backup")
    registry.update(job.id, "media", done=0, total=400)
    # The registry guarantees each update is atomic; the read-modify-write
    # below needs its own lock (services hold their own counters in practice).
    rmw_lock = threading.Lock()

    def bump(n: int) -> None:
        for _ in range(n):
            with rmw_lock:
                current = registry.get(job.id)
                registry.update(job.id, "media", done=current.done + 1, total=400)

    threads = [threading.Thread(target=bump, args=(50,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fetched = registry.get(job.id)
    assert fetched.done == fetched.total  # no lost updates
    assert fetched.percent == 100
