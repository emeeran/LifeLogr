"""In-memory job registry for long-running data operations.

Backups, restores, imports, and exports report progress through this
registry so the UI can poll a single endpoint (`GET /api/v1/jobs/{id}`)
instead of staring at a spinner. The registry is deliberately process-local
— the same model as the Ollama pull-model jobs in `routers/ai.py` — because
the backend is a single process serving both the Tauri sidecar and the web
build.

Finished jobs are retained for `JOB_TTL_SECONDS` so the frontend can pick
up the final state, then pruned lazily on the next `create`.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 300.0


def noop_reporter(
    phase: str, done: int = 0, total: int | None = None, detail: str | None = None
) -> None:
    """Default reporter — services stay callable without a job context."""


class ProgressReporter(Protocol):
    """The callback shape services accept; transport-agnostic and optional.

    A protocol (not a ``Callable`` alias) because trailing args carry defaults
    at every call site — ``report("upload")`` is as valid as
    ``report("render", i, n)`` — which a fixed-arity ``Callable`` forbids.
    """

    def __call__(
        self, phase: str, done: int = 0, total: int | None = None, detail: str | None = None
    ) -> None: ...


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running | done | failed
    phase: str = ""
    done: int = 0
    total: int | None = None
    detail: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Export jobs: the produced file (served once via GET /jobs/{id}/result).
    result_path: str | None = None
    result_name: str | None = None

    @property
    def percent(self) -> int | None:
        if self.status != "running" or not self.total:
            return None
        return min(100, round(self.done / self.total * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "percent": self.percent,
            "detail": self.detail,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobRegistry:
    """Thread-safe registry; updates arrive from worker threads."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        self._cleanup()
        job = Job(id=uuid4().hex, kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def reporter(self, job_id: str) -> ProgressReporter:
        """Reporter bound to a job; unknown/finished ids degrade to no-op."""
        return lambda phase, done=0, total=None, detail=None: self.update(
            job_id, phase, done, total, detail
        )

    def running(self) -> list[Job]:
        """Snapshot of jobs still in flight (used by the shutdown guard)."""
        self._cleanup()
        with self._lock:
            return [job for job in self._jobs.values() if job.status == "running"]

    def update(
        self,
        job_id: str,
        phase: str,
        done: int = 0,
        total: int | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.phase = phase
            job.done = done
            if total is not None:
                job.total = total
            if detail is not None:
                job.detail = detail

    def finish(self, job_id: str, detail: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.status = "done"
            job.finished_at = time.time()
            if detail is not None:
                job.detail = detail

    def finish_with_result(
        self, job_id: str, result_path: str | Path, result_name: str, detail: str | None = None
    ) -> None:
        """Finish an export job whose payload is a downloadable file."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.status = "done"
            job.finished_at = time.time()
            job.result_path = str(result_path)
            job.result_name = result_name
            if detail is not None:
                job.detail = detail

    def take_result(self, job_id: str) -> tuple[str, str] | None:
        """Return (path, download_name) if the job has a result, else None."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.result_path is None:
                return None
            return job.result_path, job.result_name or "export"

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.status = "failed"
            job.error = error
            job.finished_at = time.time()
            logger.error("Job %s (%s) failed: %s", job_id, job.kind, error)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _cleanup(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        with self._lock:
            for jid in [
                jid
                for jid, j in self._jobs.items()
                if j.finished_at is not None and j.finished_at < cutoff
            ]:
                job = self._jobs.pop(jid)
                if job.result_path:
                    try:
                        os.unlink(job.result_path)
                    except OSError:
                        pass

    def reset(self) -> None:
        """Test hook — wipe all jobs."""
        with self._lock:
            self._jobs.clear()


jobs = JobRegistry()


def start_data_job(background_tasks: Any, kind: str, runner: Callable[[ProgressReporter], Any]) -> dict[str, str]:
    """Run *runner* as a polled job behind a FastAPI BackgroundTasks.

    *runner* owns its DB session (the request's dies with the response),
    receives the job's reporter, and returns a short human detail for the
    finished job. Failure lands on the job, not the (already-sent) HTTP
    response. Returns the 202 body: ``{"job_id", "kind"}``.

    Typed loosely (``Any`` for BackgroundTasks) to keep starlette out of this
    module's import graph; every caller passes a real BackgroundTasks.
    """
    job = jobs.create(kind)
    report = jobs.reporter(job.id)

    async def _task() -> None:
        try:
            detail = await runner(report)
            jobs.finish(job.id, detail=detail)
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job.id, kind)
            jobs.fail(job.id, str(exc))

    background_tasks.add_task(_task)
    return {"job_id": job.id, "kind": kind}


def start_export_job(
    background_tasks: Any,
    kind: str,
    filename: str,
    builder: Callable[[ProgressReporter, Any], Any],
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, str]:
    """Build an export as a polled job; download via GET /jobs/{id}/result.

    *builder* receives ``(report, session)`` and returns the export bytes; the
    job writes them to a temp file, finishes with the download attached, and
    the result endpoint deletes the file after serving it. A fresh session is
    opened per job (pass ``None`` for builders that don't need the DB).
    """
    job = jobs.create(kind)
    report = jobs.reporter(job.id)

    async def _task() -> None:
        try:
            if session_factory is not None:
                async with session_factory() as session:
                    data = await builder(report, session)
            else:
                data = await builder(report, None)
            fd, tmp = tempfile.mkstemp(suffix=".export", dir=str(_export_tmp_dir()))
            os.close(fd)
            Path(tmp).write_bytes(data)
            jobs.finish_with_result(job.id, tmp, filename, detail=filename)
        except Exception as exc:
            logger.exception("Export job %s (%s) failed", job.id, kind)
            jobs.fail(job.id, str(exc))

    background_tasks.add_task(_task)
    return {"job_id": job.id, "kind": kind}


def _export_tmp_dir() -> Path:
    """Exports land under DATA_DIR/tmp so big payloads don't hit /tmp limits."""
    from app.core.config import settings

    tmp_dir = settings.DATA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir
