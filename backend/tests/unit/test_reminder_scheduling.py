"""Tests for reminder scheduling via APScheduler (sync_reminders / catch-up)."""

from datetime import datetime, timedelta, time, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.scheduler_service import SchedulerService, _reminder_due_for_catchup


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


class TestReminderDueForCatchup:
    """Direct tests for the offline catch-up predicate (previously untested).

    The predicate carries the documented naive-UTC-vs-local fix and weekday
    filtering — a regression silently drops or double-fires offline reminders
    (audit 2026-11-20)."""

    FRI = datetime(2026, 11, 20, 15, 0)  # weekday 4 (Friday), 15:00 local

    @staticmethod
    def _reminder(time_of_day: time, days: str = "0,1,2,3,4,5,6", last_fired=None):
        return SimpleNamespace(
            reminder_time=time_of_day, days_of_week=days, last_fired_at=last_fired
        )

    @pytest.fixture(autouse=True)
    def _freeze_local_now(self, monkeypatch):
        """Pin datetime.now() inside the predicate to a fixed local instant.

        The predicate reads wall-clock local time (naive) — tests pin it so
        weekday/time-of-day branches are deterministic on any host TZ.
        """
        import app.services.scheduler_service as sched_mod

        real_datetime = datetime

        class _PinnedDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001
                if tz is not None:
                    return cls.FRI.replace(tzinfo=timezone.utc).astimezone(tz)
                return cls.FRI

        _PinnedDatetime.FRI = type(self).FRI
        monkeypatch.setattr(sched_mod, "datetime", _PinnedDatetime)

    def test_not_active_today_is_not_due(self):
        assert not _reminder_due_for_catchup(
            self._reminder(time(14, 0), days="0,1,2,3"), now_utc=self.FRI
        )

    def test_time_still_ahead_is_not_due(self):
        assert not _reminder_due_for_catchup(self._reminder(time(16, 0)), now_utc=self.FRI)

    def test_passed_never_fired_is_due(self):
        assert _reminder_due_for_catchup(self._reminder(time(14, 0)), now_utc=self.FRI)

    def test_fired_today_utc_naive_is_not_due(self):
        """A naive last_fired_at is UTC (SQLite strips the offset) — fired
        today local must NOT re-fire, even though the UTC-stripped clock time
        may look like yesterday in local terms."""
        fired_local_today = self.FRI.replace(hour=9, minute=0)
        naive_utc = fired_local_today.astimezone().astimezone(timezone.utc).replace(tzinfo=None)
        assert not _reminder_due_for_catchup(
            self._reminder(time(9, 0), last_fired=naive_utc), now_utc=self.FRI
        )

    def test_fired_days_ago_is_due_again(self):
        fired = (self.FRI - timedelta(days=3)).replace(hour=9, minute=0)
        naive_utc = fired.astimezone().astimezone(timezone.utc).replace(tzinfo=None)
        assert _reminder_due_for_catchup(
            self._reminder(time(14, 0), last_fired=naive_utc), now_utc=self.FRI
        )

    def test_unparseable_days_of_week_fires_every_day(self):
        assert _reminder_due_for_catchup(
            self._reminder(time(14, 0), days="garbage"), now_utc=self.FRI
        )
