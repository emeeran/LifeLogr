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
    async def test_schema_completeness_missing_is_error(self, db_engine, db_session):
        async with db_engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(text("DROP TABLE templates"))
        res = await sc._check_schema_tables(db_session)
        assert res["status"] == "error"
        assert "templates" in res["detail"]

    @pytest.mark.asyncio
    async def test_unexpected_tables_ok_on_clean_db(self, db_session):
        # FTS5 shadow tables (entries_fts_data, …) and sqlite internals must not trip.
        res = await sc._check_unexpected_tables(db_session)
        assert res["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unexpected_tables_flags_rogue(self, db_session):
        await db_session.execute(text("CREATE TABLE legacy_leftover (x INTEGER)"))
        await db_session.commit()
        res = await sc._check_unexpected_tables(db_session)
        assert res["status"] == "warn"
        assert "legacy_leftover" in res["detail"]

    @pytest.mark.asyncio
    async def test_unexpected_tables_ignores_schema_meta(self, db_session):
        # ``_schema_meta`` is created by the inline migration system
        # (schema_version + migration_log) and is expected infrastructure, not a
        # leftover — it must not be flagged. Regression test for the false
        # "Unexpected tables: _schema_meta" warning.
        await db_session.execute(
            text("CREATE TABLE _schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        )
        await db_session.commit()
        res = await sc._check_unexpected_tables(db_session)
        assert res["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fragmentation_reports_shape(self, db_session):
        res = await sc._check_fragmentation_wal(db_session)
        assert res["id"] == "db_fragmentation"
        assert res["status"] in {"ok", "warn", "error"}
        assert "free pages" in res["detail"]

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
        assert {
            "database_structure",
            "encryption_key",
            "connection_pool",
            "data_dir",
            "unexpected_tables",
            "db_fragmentation",
        } <= ids
        assert all(c["status"] in {"ok", "warn", "error"} for c in report["checks"])
        assert sc.get_app_integrity()["ran_at"] == report["ran_at"]


    @pytest.mark.asyncio
    async def test_full_battery_self_heals_fts_drift(self, db_session, _scheduler_db):
        # ORM insert bypasses the FTS triggers the test schema lacks → drift.
        db_session.add(
            Entry(
                entry_date=date(2024, 1, 2),
                body="hello",
                title="t",
                is_deleted=False,
                is_encrypted=False,
            )
        )
        await db_session.commit()
        report = await sc.check_app_integrity()
        fts = next(c for c in report["checks"] if c["id"] == "fts_sync")
        assert fts["status"] == "ok"  # detected + rebuilt

    @pytest.mark.asyncio
    async def test_battery_runs_vacuum_on_fragmentation(self, _scheduler_db, monkeypatch):
        from unittest.mock import AsyncMock, patch

        monkeypatch.setattr(
            sc,
            "_check_fragmentation_wal",
            AsyncMock(
                return_value={
                    "id": "db_fragmentation",
                    "label": "DB fragmentation & WAL",
                    "status": "warn",
                    "detail": "80% free pages (fragmented)",
                }
            ),
        )
        with patch(
            "app.services.scheduler_service._run_incremental_vacuum", new=AsyncMock()
        ) as mock_vac:
            await sc.check_app_integrity()
        assert mock_vac.await_count >= 1


class TestRebuildSearchIndex:
    @pytest.mark.asyncio
    async def test_rebuild_repopulates_entries_fts(self, db_session):
        from app.core.database import rebuild_search_index

        db_session.add(
            Entry(
                entry_date=date(2024, 1, 3),
                body="hello world",
                title="t",
                is_deleted=False,
                is_encrypted=False,
            )
        )
        await db_session.commit()
        # Simulate drift: empty the index.
        await db_session.execute(text("DELETE FROM entries_fts"))
        await db_session.commit()
        counts = await rebuild_search_index()
        assert counts["entries"] == 1
        n = (await db_session.execute(text("SELECT COUNT(*) FROM entries_fts"))).scalar()
        assert n == 1

    @pytest.mark.asyncio
    async def test_rebuild_skips_missing_fts(self, db_engine, db_session):
        from app.core.database import rebuild_search_index

        async with db_engine.begin() as conn:
            await conn.execute(text("DROP TABLE entries_fts"))
        counts = await rebuild_search_index()  # must not raise
        assert counts["entries"] == 0


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

    @pytest.mark.asyncio
    async def test_rebuild_search_index_endpoint(self, client):
        r = await client.post("/api/v1/system/integrity/rebuild-search-index")
        assert r.status_code == 200
        body = r.json()
        assert body["ran"] is True
        assert isinstance(body["checks"], list)


class TestSchemaIntrospectionAccuracy:
    def test_models_package_registers_lazy_models(self):
        """Importing app.models registers every ORM table, including ones that
        are otherwise only imported lazily inside service functions."""
        import app.models  # noqa: F401
        from app.core.database import Base

        tables = set(Base.metadata.tables)
        assert "entry_sentiments" in tables  # only lazily imported by enrichment
        assert "entry_prompts" in tables
        assert len(tables) >= 22

    @pytest.mark.asyncio
    async def test_drop_orphan_legacy_tables(self, db_engine):
        from app.core.database import _drop_removed_feature_tables

        orphans = (
            "alembic_version", "digests", "entry_revisions",
            "ocr_results", "plugin_hooks", "plugins",
        )
        async with db_engine.begin() as conn:
            for t in orphans:
                await conn.execute(text(f"CREATE TABLE {t} (x INTEGER)"))
        async with db_engine.begin() as conn:
            await _drop_removed_feature_tables(conn)
        async with db_engine.connect() as conn:
            for t in orphans:
                exists = (
                    await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                        {"n": t},
                    )
                ).scalar()
                assert exists is None, f"{t} should have been dropped"

