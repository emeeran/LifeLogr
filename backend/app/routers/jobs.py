"""Job status + result-download endpoints for long-running data operations."""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.jobs import jobs

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    return job.to_dict()


@router.get("/{job_id}/result")
async def get_job_result(job_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    """Download a finished export job's file; deleted after serving."""
    result = jobs.take_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No result available for this job")
    path, name = result
    if not os.path.isfile(path):
        raise HTTPException(status_code=410, detail="Export result already downloaded or expired")
    background_tasks.add_task(_unlink_quietly, path)
    return FileResponse(path=path, filename=name)


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
