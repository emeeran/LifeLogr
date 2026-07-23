"""Pause/resume control for the background email + Google sync pollers."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.scheduler_service import SchedulerService


async def _noop() -> None:
    pass


@pytest.mark.asyncio
async def test_pause_then_resume_background_syncs() -> None:
    sched = AsyncIOScheduler()
    sched.start()
    try:
        sched.add_job(_noop, trigger="interval", seconds=60, id="email_sync")
        sched.add_job(_noop, trigger="interval", seconds=60, id="google_sync")

        assert SchedulerService.background_syncs_paused(sched) is False

        state = SchedulerService.set_background_syncs_paused(True, sched)
        assert state == {"email_sync": "paused", "google_sync": "paused"}
        assert SchedulerService.background_syncs_paused(sched) is True

        state = SchedulerService.set_background_syncs_paused(False, sched)
        assert state == {"email_sync": "active", "google_sync": "active"}
        assert SchedulerService.background_syncs_paused(sched) is False
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_absent_jobs_report_absent() -> None:
    """Jobs that aren't registered (e.g. Google sync not connected) report absent."""
    sched = AsyncIOScheduler()
    sched.start()
    try:
        state = SchedulerService.set_background_syncs_paused(True, sched)
        assert state == {"email_sync": "absent", "google_sync": "absent"}
        assert SchedulerService.background_syncs_paused(sched) is False
    finally:
        sched.shutdown(wait=False)
