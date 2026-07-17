"""Tests for reminder scheduling via APScheduler (sync_reminders / catch-up)."""

from unittest.mock import patch

import pytest

from app.services.scheduler_service import SchedulerService


@pytest.fixture(autouse=True)
def _clean_scheduler():
    """Reset the global scheduler singleton around each test."""
    import app.services.scheduler_service as mod

    try:
        if mod._scheduler is not None and mod._scheduler.running:
            mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None
    yield
    try:
        if mod._scheduler is not None and mod._scheduler.running:
            mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None


async def _make_reminder(client, **overrides):
    payload = {
        "title": "Write",
        "reminder_time": "21:00:00",
        "days_of_week": "0,1,2,3,4",
    }
    payload.update(overrides)
    r = await client.post("/api/v1/reminders", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestParseDaysOfWeek:
    def test_maps_ints_to_apscheduler_names(self):
        assert SchedulerService._parse_days_of_week("0,6") == "mon,sun"

    def test_full_week_default_on_garbage(self):
        assert SchedulerService._parse_days_of_week("") == ("mon,tue,wed,thu,fri,sat,sun")

    def test_dedupes_and_ignores_out_of_range(self):
        # 0 (mon) duplicated, 9 out of range ignored
        assert SchedulerService._parse_days_of_week("0,0,9") == "mon"


class TestReminderSyncsOnCrud:
    """CRUD through the router must reconcile scheduler jobs."""

    async def test_create_schedules_job(self, client):
        with patch.object(SchedulerService, "sync_reminders") as mock_sync:
            mock_sync.return_value = 0
            await _make_reminder(client)
        assert mock_sync.await_count == 1

    async def test_update_resyncs_jobs(self, client):
        rem = await _make_reminder(client)
        with patch.object(SchedulerService, "sync_reminders") as mock_sync:
            mock_sync.return_value = 0
            r = await client.patch(f"/api/v1/reminders/{rem['id']}", json={"title": "New"})
            assert r.status_code == 200
        assert mock_sync.await_count == 1

    async def test_delete_resyncs_jobs(self, client):
        rem = await _make_reminder(client)
        with patch.object(SchedulerService, "sync_reminders") as mock_sync:
            mock_sync.return_value = 0
            r = await client.delete(f"/api/v1/reminders/{rem['id']}")
            assert r.status_code == 204
        assert mock_sync.await_count == 1


class TestSyncReminders:
    @staticmethod
    def _patch_session(test_session):
        """Make sync_reminders use the test's DB session instead of the app default."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _factory():
            yield test_session

        return patch("app.core.database.async_session", _factory)

    async def test_sync_reminders_registers_active_only(self, db_session):
        """sync_reminders adds jobs for active reminders and prunes stale ones."""
        from datetime import time

        from app.models.reminder import Reminder

        db_session.add_all(
            [
                Reminder(title="A", reminder_time=time(9, 0), days_of_week="0,1,2", is_active=True),
                Reminder(title="B", reminder_time=time(10, 0), days_of_week="3,4", is_active=False),
            ]
        )
        await db_session.commit()

        await SchedulerService.start()
        try:
            with self._patch_session(db_session):
                count = await SchedulerService.sync_reminders()
            assert count == 1  # only the active reminder
            sched = SchedulerService.get_scheduler()
            assert sched.get_job("reminder_1") is not None
            assert sched.get_job("reminder_2") is None
        finally:
            await SchedulerService.shutdown()

    async def test_unschedule_reminder_removes_job(self, db_session):
        from datetime import time

        from app.models.reminder import Reminder

        db_session.add(Reminder(title="X", reminder_time=time(9, 0), is_active=True))
        await db_session.commit()
        await SchedulerService.start()
        try:
            with self._patch_session(db_session):
                await SchedulerService.sync_reminders()
            sched = SchedulerService.get_scheduler()
            assert sched.get_job("reminder_1") is not None
            await SchedulerService.unschedule_reminder(1)
            assert sched.get_job("reminder_1") is None
        finally:
            await SchedulerService.shutdown()


class TestCatchup:
    async def test_catchup_swallows_errors(self):
        """schedule_catchup must never raise even if the DB is unavailable."""
        with patch("app.core.database.async_session", side_effect=RuntimeError):
            # Should not raise.
            await SchedulerService.schedule_catchup()
