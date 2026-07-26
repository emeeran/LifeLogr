"""Startup self-checks: data integrity + backup functionality."""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.startup_checks as sc
from app.core import security
from app.core.config import settings
from app.models.backup import BackupConfig
from app.models.entry import Entry
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
    sc._app_integrity_result.update(
        ran=False, ran_at=None, checks=[], summary={"ok": 0, "warn": 0, "error": 0}
    )
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


def _backup_config(credentials_encrypted: str) -> BackupConfig:
    return BackupConfig(
        provider="google_drive",
        credentials_encrypted=credentials_encrypted,
    )


class TestCheckAppIntegrity:
    @pytest.mark.asyncio
    async def test_encryption_key_default_is_error(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "change-me-before-production")
        res = await sc._check_encryption_key(db_session)
        assert res["status"] == "error"

    @pytest.mark.asyncio
    async def test_encryption_key_valid_credential_ok(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")  # bypass the default guard
        db_session.add(_backup_config(security.encrypt("secret")))
        await db_session.commit()
        res = await sc._check_encryption_key(db_session)
        assert res["status"] == "ok"

    @pytest.mark.asyncio
    async def test_encryption_key_undecryptable_is_error(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")
        db_session.add(_backup_config("not-a-valid-encrypted-token"))
        await db_session.commit()
        res = await sc._check_encryption_key(db_session)
        assert res["status"] == "error"
        assert "backup_config" in res["detail"]

    @pytest.mark.asyncio
    async def test_schema_tables_ok(self, db_session):
        assert (await sc._check_schema_tables(db_session))["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fts_sync_drift_warns(self, db_session):
        # Direct insert bypasses the app-level FTS triggers the test schema lacks.
        db_session.add(
            Entry(
                entry_date=date(2024, 1, 1),
                body="hi",
                title="t",
                is_deleted=False,
                is_encrypted=False,
            )
        )
        await db_session.commit()
        assert (await sc._check_fts_sync(db_session))["status"] == "warn"

    @pytest.mark.asyncio
    async def test_structure_ok(self, db_session):
        assert (await sc._check_structure(db_session))["status"] == "ok"

    def test_connection_pool_warns_when_size_one(self, monkeypatch):
        monkeypatch.setattr(settings, "DB_POOL_SIZE", 1)
        assert sc._check_connection_pool()["status"] == "warn"

    def test_connection_pool_ok_by_default(self):
        assert settings.DB_POOL_SIZE > 1
        assert sc._check_connection_pool()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_full_battery_returns_report(self, _scheduler_db):
        report = await sc.check_app_integrity()
        assert report["ran"] is True
        assert report["ran_at"]
        assert len(report["checks"]) >= 8
        assert set(report["summary"]) == {"ok", "warn", "error"}
        ids = {c["id"] for c in report["checks"]}
        assert {"database_structure", "encryption_key", "connection_pool", "data_dir"} <= ids
        assert all(c["status"] in {"ok", "warn", "error"} for c in report["checks"])
        assert sc.get_app_integrity()["ran_at"] == report["ran_at"]


class TestSystemIntegrityEndpoint:
    @pytest.mark.asyncio
    async def test_get_returns_cached_report(self, client):
        await sc.check_app_integrity()  # populate the cache
        r = await client.get("/api/v1/system/integrity")
        assert r.status_code == 200
        body = r.json()
        assert body["ran"] is True
        assert isinstance(body["checks"], list)

    @pytest.mark.asyncio
    async def test_post_reruns_live(self, client):
        r = await client.post("/api/v1/system/integrity")
        assert r.status_code == 200
        assert r.json()["ran"] is True

