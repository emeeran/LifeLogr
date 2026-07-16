"""Startup self-checks: data integrity + backup functionality."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.startup_checks as sc
from app.services.scheduler_service import SchedulerService, _mark_backup_run


@pytest_asyncio.fixture
async def _scheduler_db(db_engine, monkeypatch):
    """Point the scheduler's async_session at the per-test DB.

    Both startup checks resolve ``async_session`` lazily from ``app.core.database``,
    so patching the module attribute makes them read/write the same temp DB the
    fixtures use.
    """
    import app.core.database as dbmod

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbmod, "async_session", factory)
    yield


@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    """Reset the scheduler singleton and the stashed startup-check results."""
    import app.services.scheduler_service as mod

    store = tmp_path / ".backup-schedule.json"
    monkeypatch.setattr(mod, "_schedule_store_path", lambda: store)
    try:
        if mod._scheduler is not None and mod._scheduler.running:
            mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None

    # Reset stashed results so each test sees a clean baseline.
    sc._integrity_result.update(ran=False, ok=True, fk_violations=0)
    sc._backup_result.update(ran=False, scheduled=None, last_run=None, stale=None)
    yield

    try:
        if mod._scheduler is not None and mod._scheduler.running:
            mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    mod._scheduler = None


def _ensure_scheduler_running() -> None:
    sched = SchedulerService.get_scheduler()
    if not sched.running:
        sched.start()


class TestCheckDataIntegrity:
    @pytest.mark.asyncio
    async def test_clean_db_reports_ok(self, _reset_state, _scheduler_db):
        await sc.check_data_integrity()
        res = sc.get_integrity_status()
        assert res["ran"] is True
        assert res["ok"] is True
        assert res["fk_violations"] == 0

    @pytest.mark.asyncio
    async def test_orphan_fk_is_flagged(self, db_engine, _reset_state, _scheduler_db):
        # Create a referential orphan: a snapshot whose config_id doesn't exist.
        # FK enforcement is ON, so disable it for the raw insert; the check's
        # PRAGMA foreign_key_check scans existing rows regardless of the pragma.
        async with db_engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(
                text(
                    "INSERT INTO backup_snapshots "
                    "(config_id, status, entries_synced, media_synced) "
                    "VALUES (999999, 'completed', 0, 0)"
                )
            )

        await sc.check_data_integrity()
        res = sc.get_integrity_status()
        assert res["ran"] is True
        assert res["ok"] is False
        assert res["fk_violations"] >= 1


class TestCheckBackupHealth:
    @pytest.mark.asyncio
    async def test_no_schedule(self, _reset_state, _scheduler_db):
        _ensure_scheduler_running()
        await sc.check_backup_health()
        res = sc.get_backup_status()
        assert res["ran"] is True
        assert res["scheduled"] is False

    @pytest.mark.asyncio
    async def test_healthy_schedule_is_stale_until_first_backup(
        self, db_session, _reset_state, _scheduler_db
    ):
        _ensure_scheduler_running()
        await SchedulerService(db_session).schedule_backup(
            cron_expr="0 2 * * *", backup_path="/tmp/x", retention=3
        )
        await sc.check_backup_health()
        res = sc.get_backup_status()
        assert res["ran"] is True
        assert res["scheduled"] is True
        # No backup has ever run → flagged stale (accurate: it is unbacked-up).
        assert res["stale"] is True

    @pytest.mark.asyncio
    async def test_self_heal_missing_job(self, db_session, _reset_state, _scheduler_db):
        """Silent-stop regression: schedule present, job gone → re-registered."""
        from unittest.mock import patch

        _ensure_scheduler_running()
        await SchedulerService(db_session).schedule_backup(
            cron_expr="0 2 * * *", backup_path="/tmp/x", retention=3
        )
        sched = SchedulerService.get_scheduler()
        assert sched.get_job("auto_backup") is not None

        # Simulate the job being lost (e.g. _restore_backup_schedule no-oped).
        sched.remove_job("auto_backup")
        assert sched.get_job("auto_backup") is None

        with patch.object(sc.logger, "error") as mock_err:
            await sc.check_backup_health()
        assert mock_err.called  # logged the ERROR about the missing job

        # Self-healed: the job is back and status reflects it.
        assert sched.get_job("auto_backup") is not None
        assert sc.get_backup_status()["scheduled"] is True

    @pytest.mark.asyncio
    async def test_recent_backup_not_stale(self, db_session, _reset_state, _scheduler_db):
        _ensure_scheduler_running()
        await SchedulerService(db_session).schedule_backup(
            cron_expr="0 2 * * *", backup_path="/tmp/x", retention=3
        )
        await _mark_backup_run()  # last_run ≈ now
        await sc.check_backup_health()
        res = sc.get_backup_status()
        assert res["scheduled"] is True
        assert res["stale"] is False
