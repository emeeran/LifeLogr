"""Unit tests for SchedulerService — local and cloud backup scheduling."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import encrypt
from app.models.backup import BackupConfig
from app.services.scheduler_service import SchedulerService, _run_cloud_backup


@pytest.fixture(autouse=True)
def _clean_scheduler():
    """Reset the global scheduler singleton before and after each test.

    APScheduler's AsyncIOScheduler binds to the current event loop, so
    the singleton MUST be reset between tests to avoid "Event loop is closed"
    errors when pytest-asyncio creates a new loop per test.
    """
    import app.services.scheduler_service as mod

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
            if mod._scheduler.running:
                mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None


class TestScheduleBackupLocal:
    """Tests for local filesystem backup scheduling (config_id=None)."""

    @pytest.mark.asyncio
    async def test_schedule_local_backup(self, db_session, _clean_scheduler):
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
    async def test_unschedule_backup(self, db_session, _clean_scheduler):
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
    async def test_schedule_cloud_backup(self, db_session, _clean_scheduler):
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
    async def test_reschedule_replaces_existing_job(self, db_session, _clean_scheduler):
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
