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
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 300.0


def noop_reporter(
    phase: str, done: int = 0, total: int | None = None, detail: str | None = None
) -> None:
    """Default reporter — services stay callable without a job context."""


# The callback shape services accept; transport-agnostic and optional.
ProgressReporter = Callable[[str, int, int | None, str | None], None]


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
                del self._jobs[jid]

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
