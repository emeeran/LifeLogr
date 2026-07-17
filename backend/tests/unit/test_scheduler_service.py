"""Unit tests for SchedulerService — local and cloud backup scheduling."""

import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import encrypt
from app.models.backup import BackupConfig
from app.services.scheduler_service import (
    SchedulerService,
    _clear_legacy_schedule,
    _get_active_schedule,
    _last_scheduled_occurrence,
    _load_legacy_schedule,
    _mark_backup_run,
    _run_cloud_backup,
    _save_schedule,
)


@pytest.fixture(autouse=True)
def _clean_scheduler(tmp_path, monkeypatch):
    """Reset the global scheduler singleton before and after each test.

    APScheduler's AsyncIOScheduler binds to the current event loop, so
    the singleton MUST be reset between tests to avoid "Event loop is closed"
    errors when pytest-asyncio creates a new loop per test. The legacy schedule
    store is redirected to a temp path so tests never touch the real data dir.
    """
    import app.services.scheduler_service as mod

    store = tmp_path / ".backup-schedule.json"
    monkeypatch.setattr(mod, "_schedule_store_path", lambda: store)

    # Teardown any leftover state from previous test modules
    try:
        if mod._scheduler is not None:
            if mod._scheduler.running:
                mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None

    yield

    # Teardown after this test
    try:
        if mod._scheduler is not None:
            if mod._scheduler.get_job("auto_backup"):
                mod._scheduler.remove_job("auto_backup")
            if mod._scheduler.get_job("backup_catchup"):
                mod._scheduler.remove_job("backup_catchup")
            if mod._scheduler.running:
                mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None


@pytest_asyncio.fixture
async def _scheduler_db(db_engine, monkeypatch):
    """Point the scheduler's async_session at the per-test DB.

    The DB-backed schedule helpers import ``async_session`` from
    ``app.core.database`` lazily; patching the module attribute makes them
    read/write the same temp DB that ``db_session`` sees, so tests can set up
    and assert via ``db_session``.
    """
    import app.core.database as dbmod

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbmod, "async_session", factory)
    yield


class TestScheduleBackupLocal:
    """Tests for local filesystem backup scheduling (config_id=None)."""

    @pytest.mark.asyncio
    async def test_schedule_local_backup(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)
        result = await svc.schedule_backup(
            cron_expr="0 2 * * *",
            backup_path="/tmp/lifelogr-test-backups",
            retention=5,
        )

        assert result["job_id"] == "auto_backup"
        assert result["cron"] == "0 2 * * *"
        assert result["config_id"] is None
        assert result["next_run"] is not None

        sched = SchedulerService.get_scheduler()
        job = sched.get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"backup_path": "/tmp/lifelogr-test-backups", "retention": 5}

    @pytest.mark.asyncio
    async def test_schedule_local_requires_backup_path(self, db_session, _clean_scheduler):
        svc = SchedulerService(db_session)
        with pytest.raises(ValueError, match="backup_path is required"):
            await svc.schedule_backup(
                cron_expr="0 2 * * *",
                backup_path=None,
                config_id=None,
            )

    @pytest.mark.asyncio
    async def test_invalid_cron_expression(self, db_session, _clean_scheduler):
        svc = SchedulerService(db_session)
        with pytest.raises(ValueError, match="Invalid cron expression"):
            await svc.schedule_backup(
                cron_expr="not-a-cron",
                backup_path="/tmp/backups",
            )

    @pytest.mark.asyncio
    async def test_unschedule_backup(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)
        await svc.schedule_backup(
            cron_expr="0 2 * * *",
            backup_path="/tmp/backups",
        )
        result = await svc.unschedule_backup()
        assert result["removed"] is True

        sched = SchedulerService.get_scheduler()
        assert sched.get_job("auto_backup") is None

    @pytest.mark.asyncio
    async def test_get_status_no_job(self, db_session, _clean_scheduler):
        svc = SchedulerService(db_session)
        status = await svc.get_status()
        assert status["backup_scheduled"] is False
        assert status["next_run"] is None


class TestScheduleBackupCloud:
    """Tests for cloud backup scheduling (config_id provided)."""

    @pytest.mark.asyncio
    async def test_schedule_cloud_backup(self, db_session, _clean_scheduler, _scheduler_db):
        # Seed a Google Drive config
        creds = {
            "client_id": "test-id",
            "client_secret": "test-secret",
            "access_token": "token",
            "refresh_token": "refresh",
            "token_expiry": str(time.time() + 3600),
        }
        config = BackupConfig(
            provider="google_drive",
            credentials_encrypted=encrypt(json.dumps(creds)),
        )
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)

        svc = SchedulerService(db_session)
        result = await svc.schedule_backup(
            cron_expr="0 3 * * *",
            config_id=config.id,
        )

        assert result["job_id"] == "auto_backup"
        assert result["cron"] == "0 3 * * *"
        assert result["config_id"] == config.id

        sched = SchedulerService.get_scheduler()
        job = sched.get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"config_id": config.id}
        assert job.func_ref is not None  # points to _run_cloud_backup

    @pytest.mark.asyncio
    async def test_reschedule_replaces_existing_job(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)

        # Schedule local first
        await svc.schedule_backup(
            cron_expr="0 2 * * *",
            backup_path="/tmp/backups",
        )
        # Replace with cloud
        await svc.schedule_backup(
            cron_expr="0 3 * * *",
            config_id=1,
        )

        sched = SchedulerService.get_scheduler()
        job = sched.get_job("auto_backup")
        # Only one job, and it's the cloud one
        assert job.kwargs == {"config_id": 1}


class TestRunCloudBackup:
    """Tests for the _run_cloud_backup standalone function."""

    @pytest.mark.asyncio
    async def test_cloud_backup_calls_backup_service(self):
        """Verify _run_cloud_backup delegates to BackupService.run_backup()."""
        mock_snapshot = type("Snapshot", (), {"id": 42, "status": "completed"})()

        with (
            patch("app.core.database.async_session") as mock_sf,
            patch("app.services.backup_service.BackupService") as MockSvc,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            MockSvc.return_value.run_backup = AsyncMock(return_value=mock_snapshot)

            await _run_cloud_backup(config_id=7)

            MockSvc.assert_called_once_with(mock_session)
            MockSvc.return_value.run_backup.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_cloud_backup_logs_error_without_raising(self):
        """Verify _run_cloud_backup swallows exceptions (scheduler must not crash)."""
        with (
            patch("app.core.database.async_session") as mock_sf,
            patch("app.services.backup_service.BackupService") as MockSvc,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            MockSvc.return_value.run_backup = AsyncMock(
                side_effect=Exception("Google Drive API error")
            )

            # Should NOT raise — errors are logged, not propagated
            await _run_cloud_backup(config_id=7)


def _ensure_scheduler_running() -> None:
    sched = SchedulerService.get_scheduler()
    if not sched.running:
        sched.start()


class TestSchedulePersistence:
    """The active schedule is persisted to the DB (source of truth) and so
    survives app restarts (APScheduler's in-memory job store is lost on exit)."""

    @pytest.mark.asyncio
    async def test_schedule_local_persists_to_db(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)
        await svc.schedule_backup(cron_expr="0 2 * * *", backup_path="/tmp/x", retention=7)
        active = await _get_active_schedule()
        assert active is not None
        assert active.cron == "0 2 * * *"
        assert active.backup_path == "/tmp/x"
        assert active.retention == 7
        assert active.config_id is None

    @pytest.mark.asyncio
    async def test_schedule_cloud_persists_to_db(self, db_session, _clean_scheduler, _scheduler_db):
        config = BackupConfig(
            provider="google_drive",
            credentials_encrypted=encrypt("{}"),
        )
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)

        svc = SchedulerService(db_session)
        await svc.schedule_backup(cron_expr="0 3 * * *", config_id=config.id)
        active = await _get_active_schedule()
        assert active is not None
        assert active.cron == "0 3 * * *"
        assert active.config_id == config.id
        assert active.backup_path is None

    @pytest.mark.asyncio
    async def test_unschedule_clears_db(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)
        await svc.schedule_backup(cron_expr="0 2 * * *", backup_path="/tmp/x")
        assert (await _get_active_schedule()) is not None

        await svc.unschedule_backup()
        assert (await _get_active_schedule()) is None

    @pytest.mark.asyncio
    async def test_reschedule_preserves_last_run(self, db_session, _clean_scheduler, _scheduler_db):
        svc = SchedulerService(db_session)
        await svc.schedule_backup(cron_expr="0 2 * * *", backup_path="/tmp/x")
        await _mark_backup_run()
        active = await _get_active_schedule()
        assert active is not None
        assert active.last_run_at is not None

        # Re-saving the schedule must not wipe the run history.
        await svc.schedule_backup(cron_expr="30 3 * * *", backup_path="/tmp/x")
        active = await _get_active_schedule()
        assert active is not None
        assert active.cron == "30 3 * * *"
        assert active.last_run_at is not None


class TestRestoreBackupSchedule:
    """_restore_backup_schedule re-registers jobs after a restart (DB-backed)."""

    @pytest.mark.asyncio
    async def test_noop_when_nothing_persisted(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        await SchedulerService._restore_backup_schedule()
        assert SchedulerService.get_scheduler().get_job("auto_backup") is None

    @pytest.mark.asyncio
    async def test_restores_local_job_from_db(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        await _save_schedule({"cron": "0 2 * * *", "backup_path": "/tmp/x", "retention": 3})
        await SchedulerService._restore_backup_schedule()
        job = SchedulerService.get_scheduler().get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"backup_path": "/tmp/x", "retention": 3}

    @pytest.mark.asyncio
    async def test_restores_cloud_job_when_config_exists(
        self, db_session, _clean_scheduler, _scheduler_db
    ):
        _ensure_scheduler_running()
        config = BackupConfig(provider="google_drive", credentials_encrypted=encrypt("{}"))
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)
        await _save_schedule({"cron": "0 3 * * *", "config_id": config.id})

        await SchedulerService._restore_backup_schedule()

        job = SchedulerService.get_scheduler().get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"config_id": config.id}

    @pytest.mark.asyncio
    async def test_clears_when_config_gone(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        # config_id 999 doesn't exist → schedule is stale and must be dropped.
        await _save_schedule({"cron": "0 3 * * *", "config_id": 999})

        await SchedulerService._restore_backup_schedule()

        assert SchedulerService.get_scheduler().get_job("auto_backup") is None
        assert (await _get_active_schedule()) is None  # stale schedule dropped

    @pytest.mark.asyncio
    async def test_survives_legacy_json_loss_via_db(
        self, db_session, _clean_scheduler, _scheduler_db
    ):
        """Core regression: a schedule stored in the DB is restored even when the
        legacy JSON file is gone — the original silent-stop bug."""
        _ensure_scheduler_running()
        svc = SchedulerService(db_session)
        await svc.schedule_backup(cron_expr="0 2 * * *", backup_path="/tmp/x", retention=3)

        # Simulate the loss that broke the installed app: no legacy file at all.
        _clear_legacy_schedule()
        assert _load_legacy_schedule() is None

        # Simulate a restart: drop the in-memory job, then restore.
        SchedulerService.get_scheduler().remove_job("auto_backup")
        assert SchedulerService.get_scheduler().get_job("auto_backup") is None
        await SchedulerService._restore_backup_schedule()

        job = SchedulerService.get_scheduler().get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"backup_path": "/tmp/x", "retention": 3}

    @pytest.mark.asyncio
    async def test_migrates_legacy_json_to_db(self, _clean_scheduler, _scheduler_db):
        """One-time upgrade path: a pre-upgrade legacy JSON file is migrated into
        the DB and then removed."""
        import app.services.scheduler_service as mod

        _ensure_scheduler_running()
        store = mod._schedule_store_path()  # tmp path (redirected by _clean_scheduler)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(
            json.dumps({"cron": "0 5 * * *", "backup_path": "/tmp/y", "retention": 4})
        )
        assert (await _get_active_schedule()) is None

        await SchedulerService._restore_backup_schedule()

        job = SchedulerService.get_scheduler().get_job("auto_backup")
        assert job is not None
        assert job.kwargs == {"backup_path": "/tmp/y", "retention": 4}
        # DB now holds the schedule ...
        active = await _get_active_schedule()
        assert active is not None
        assert active.cron == "0 5 * * *"
        # ... and the legacy file has been removed.
        assert _load_legacy_schedule() is None


class TestBackupCatchup:
    """Missed backups should run once on next startup (desktop app offline)."""

    @pytest.mark.asyncio
    async def test_runs_local_when_stale(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        await _save_schedule({"cron": "0 2 * * *", "backup_path": "/tmp/x", "retention": 3})
        with patch("app.services.scheduler_service._run_backup", new=AsyncMock()) as mock_run:
            await SchedulerService._backup_catchup()
            mock_run.assert_awaited_once_with("/tmp/x", 3)

    @pytest.mark.asyncio
    async def test_skips_when_already_ran(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        await _save_schedule({"cron": "0 2 * * *", "backup_path": "/tmp/x", "retention": 3})
        await _mark_backup_run()  # last_run_at ≈ now → not stale
        with patch("app.services.scheduler_service._run_backup", new=AsyncMock()) as mock_run:
            await SchedulerService._backup_catchup()
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_cloud_when_stale(self, _clean_scheduler, _scheduler_db):
        _ensure_scheduler_running()
        await _save_schedule({"cron": "0 3 * * *", "config_id": 11})
        with patch(
            "app.services.scheduler_service._run_cloud_backup", new=AsyncMock()
        ) as mock_run:
            await SchedulerService._backup_catchup()
            mock_run.assert_awaited_once_with(11)


class TestLastScheduledOccurrence:
    """Cron → most-recent-past-fire math for the daily/weekly/monthly forms."""

    def test_daily_after_time(self):
        now = datetime(2026, 7, 7, 10, 0)
        assert _last_scheduled_occurrence("0 2 * * *", now) == datetime(2026, 7, 7, 2, 0)

    def test_daily_before_time_falls_to_yesterday(self):
        now = datetime(2026, 7, 7, 1, 0)  # 01:00, before today's 02:00
        assert _last_scheduled_occurrence("0 2 * * *", now) == datetime(2026, 7, 6, 2, 0)

    def test_weekly_picks_correct_weekday(self):
        now = datetime(2026, 7, 7, 12, 0)  # arbitrary Tuesday
        res = _last_scheduled_occurrence("0 2 * * 0", now)  # 0 = Monday
        assert res is not None
        assert res <= now
        assert res.weekday() == 0
        assert (res.hour, res.minute) == (2, 0)
        assert (res + timedelta(days=7)) > now  # truly the most recent

    def test_monthly_first_of_month(self):
        now = datetime(2026, 7, 15, 10, 0)
        assert _last_scheduled_occurrence("0 2 1 * *", now) == datetime(2026, 7, 1, 2, 0)

    def test_invalid_cron_returns_none(self):
        assert _last_scheduled_occurrence("nope", datetime.now()) is None
