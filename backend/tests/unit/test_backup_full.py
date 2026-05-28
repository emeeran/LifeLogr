"""Comprehensive tests for backup, auto-backup scheduling, and restore.

Covers:
  - Local export / import round-trip (DB + media)
  - Corrupt / non-SQLite archive rejection
  - Path traversal rejection
  - Import with media-only (no DB)
  - Scheduler CRUD (schedule, status, unschedule)
  - Restore utility: validate_extracted_db, _atomic_write, _atomic_media_swap
  - Backup config CRUD via HTTP
  - Snapshot listing
"""

import io
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.restore import (
    _atomic_media_swap,
    _atomic_write,
    _check_expected_tables,
    _check_integrity,
    _is_sqlite_file,
    validate_extracted_db,
)


# ── Scheduler state cleanup ──────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_scheduler():
    """Ensure the global scheduler is clean before and after every test."""
    from app.services.scheduler_service import SchedulerService, _scheduler

    # Reset the global scheduler instance before each test
    import app.services.scheduler_service as sched_mod
    if sched_mod._scheduler is not None and sched_mod._scheduler.running:
        sched_mod._scheduler.shutdown(wait=False)
    sched_mod._scheduler = None
    yield
    if sched_mod._scheduler is not None and sched_mod._scheduler.running:
        sched_mod._scheduler.shutdown(wait=False)
    sched_mod._scheduler = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_valid_db(path: Path) -> Path:
    """Create a minimal valid SQLite DB with an ``entries`` table at *path*."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY,
            entry_date DATE NOT NULL,
            body TEXT NOT NULL,
            is_deleted BOOLEAN NOT NULL DEFAULT 0,
            is_encrypted BOOLEAN NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2025-01-01', 'hello world', 0, 0)"
    )
    conn.commit()
    conn.close()
    return path


def _make_archive_from_bytes(db_content: bytes, name: str = "diarium.diarium") -> bytes:
    """Build a .tar.gz containing a DB file with the given raw bytes."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(db_content)
        tar.addfile(info, io.BytesIO(db_content))
    return buf.getvalue()


# ── Restore utility unit tests ───────────────────────────────────────────────


class TestValidateExtractedDb:
    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            validate_extracted_db(tmp_path / "nope.db")

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.db"
        empty.touch()
        with pytest.raises(ValueError, match="empty"):
            validate_extracted_db(empty)

    def test_rejects_non_sqlite_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "junk.db"
        bad.write_text("this is not a sqlite file")
        with pytest.raises(ValueError, match="not a valid SQLite"):
            validate_extracted_db(bad)

    def test_rejects_db_missing_entries_table(self, tmp_path: Path) -> None:
        db = tmp_path / "no_entries.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="missing expected tables"):
            validate_extracted_db(db)

    def test_accepts_valid_db(self, tmp_path: Path) -> None:
        db = _make_valid_db(tmp_path / "good.db")
        validate_extracted_db(db)  # should not raise


class TestIsSqliteFile:
    def test_detects_sqlite_header(self, tmp_path: Path) -> None:
        db = _make_valid_db(tmp_path / "test.db")
        assert _is_sqlite_file(db) is True

    def test_rejects_non_sqlite(self, tmp_path: Path) -> None:
        p = tmp_path / "data"
        p.write_text("hello")
        assert _is_sqlite_file(p) is False

    def test_returns_false_for_missing(self, tmp_path: Path) -> None:
        assert _is_sqlite_file(tmp_path / "missing") is False


class TestAtomicWrite:
    def test_replaces_destination(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        dst = tmp_path / "dst.db"
        _make_valid_db(src)
        dst.write_text("old content")

        _atomic_write(src, dst)
        assert dst.read_bytes()[:16] == b"SQLite format 3\x00"
        # tmp file should be cleaned up
        assert not dst.with_suffix(dst.suffix + ".tmp").exists()

    def test_no_partial_on_failure(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        src.write_text("good")
        dst = tmp_path / "sub" / "nested" / "dst.db"
        # dst parent doesn't exist → copy2 will fail
        with pytest.raises(Exception):
            _atomic_write(src, dst)
        # No .tmp littered
        assert not list(tmp_path.rglob("*.tmp"))


class TestAtomicMediaSwap:
    def test_swaps_directories(self, tmp_path: Path) -> None:
        src = tmp_path / "new_media"
        src.mkdir()
        (src / "photo.jpg").write_bytes(b"jpgdata")

        dst = tmp_path / "media"
        dst.mkdir()
        (dst / "old.jpg").write_bytes(b"olddata")

        _atomic_media_swap(src, dst)

        assert (dst / "photo.jpg").read_bytes() == b"jpgdata"
        assert not (dst / "old.jpg").exists()
        # .bak should be cleaned up
        assert not (tmp_path / "media.bak").exists()

    def test_rollback_on_copytree_failure(self, tmp_path: Path) -> None:
        """If copytree fails, original dst is restored."""
        src = tmp_path / "new_media"
        src.mkdir()
        (src / "file.txt").write_text("new")

        dst = tmp_path / "media"
        dst.mkdir()
        (dst / "original.txt").write_text("original")

        with patch("app.core.restore.shutil.copytree", side_effect=PermissionError("fail")):
            with pytest.raises(PermissionError):
                _atomic_media_swap(src, dst)

        # Original data should be restored
        assert (dst / "original.txt").read_text() == "original"


class TestCheckIntegrity:
    def test_passes_for_valid_db(self, tmp_path: Path) -> None:
        db = _make_valid_db(tmp_path / "ok.db")
        _check_integrity(db)  # no exception

    def test_detects_corruption(self, tmp_path: Path) -> None:
        """Truncating the DB file produces a detectable corruption."""
        db = _make_valid_db(tmp_path / "bad.db")
        raw = db.read_bytes()
        db.write_bytes(raw[: len(raw) // 2])
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            _check_integrity(db)


class TestCheckExpectedTables:
    def test_passes_when_entries_exists(self, tmp_path: Path) -> None:
        db = _make_valid_db(tmp_path / "ok.db")
        _check_expected_tables(db)

    def test_fails_when_entries_missing(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="missing expected tables"):
            _check_expected_tables(db)


# ── HTTP-level backup tests ──────────────────────────────────────────────────


class TestBackupConfigCrud:
    async def test_create_config(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/backup/config",
            json={
                "provider": "webdav",
                "credentials": {
                    "url": "https://dav.example.com",
                    "username": "u",
                    "password": "p",
                },
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["provider"] == "webdav"
        assert "id" in data

    async def test_list_configs(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/backup/config",
            json={
                "provider": "webdav",
                "credentials": {"url": "https://dav.example.com"},
            },
        )
        r = await client.get("/api/v1/backup/config")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_delete_config(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/backup/config",
            json={
                "provider": "webdav",
                "credentials": {"url": "https://dav.example.com"},
            },
        )
        config_id = r.json()["id"]
        dr = await client.delete(f"/api/v1/backup/config/{config_id}")
        assert dr.status_code == 204

    async def test_test_connection_missing_config(self, client: AsyncClient) -> None:
        r = await client.post("/api/v1/backup/config/9999/test")
        assert r.status_code == 404


class TestBackupSnapshots:
    async def test_list_snapshots_empty(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/backup/snapshots")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_snapshots_with_config_filter(
        self, client: AsyncClient
    ) -> None:
        r = await client.get("/api/v1/backup/snapshots?config_id=999")
        assert r.status_code == 200


# ── Export / Import tests ────────────────────────────────────────────────────


class TestExportImport:
    async def test_export_returns_tar_gz(
        self, client: AsyncClient, db_engine
    ) -> None:
        """Export endpoint returns a valid gzip archive with diarium.diarium."""
        async def _noop_checkpoint(path: Path) -> None:
            pass

        db_file = settings.db_path
        db_file.parent.mkdir(parents=True, exist_ok=True)
        if not db_file.exists():
            _make_valid_db(db_file)

        with patch("app.core.restore.checkpoint_wal", side_effect=_noop_checkpoint):
            r = await client.get("/api/v1/backup/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/gzip"
        buf = io.BytesIO(r.content)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
            assert "diarium.diarium" in names

    async def test_export_contains_entry_data(
        self, client: AsyncClient, db_session: AsyncSession, db_engine
    ) -> None:
        """Export archives the live DB including user entries."""
        async def _noop_checkpoint(path: Path) -> None:
            pass

        # Delete any leftover DB and create fresh
        db_file = settings.db_path
        if db_file.exists():
            db_file.unlink()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        _make_valid_db(db_file)

        # Insert test data directly into the file
        conn = sqlite3.connect(str(db_file))
        try:
            conn.execute(
                "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2025-01-15', 'export-test', 0, 0)"
            )
            conn.commit()
        finally:
            conn.close()

        with patch("app.core.restore.checkpoint_wal", side_effect=_noop_checkpoint):
            r = await client.get("/api/v1/backup/export")
        assert r.status_code == 200

        # Verify the exported DB contains our entry
        buf = io.BytesIO(r.content)
        extract_dir = tempfile.mkdtemp()
        try:
            with tarfile.open(fileobj=buf, mode="r:gz") as tar:
                tar.extractall(extract_dir)
            conn2 = sqlite3.connect(os.path.join(extract_dir, "diarium.diarium"))
            rows = conn2.execute("SELECT body FROM entries WHERE body='export-test'").fetchall()
            conn2.close()
            assert len(rows) == 1
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    async def test_import_rejects_path_traversal(
        self, client: AsyncClient
    ) -> None:
        """Archive with ../ in member names is rejected with 400."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"junk"
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("evil.tar.gz", buf.read(), "application/gzip")},
        )
        assert r.status_code == 400
        assert "path traversal" in r.json()["detail"].lower()

    async def test_import_rejects_absolute_path(
        self, client: AsyncClient
    ) -> None:
        """Archive with absolute paths is rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"junk"
            info = tarfile.TarInfo(name="/etc/shadow")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("evil.tar.gz", buf.read(), "application/gzip")},
        )
        assert r.status_code == 400

    async def test_import_rejects_non_sqlite_db(self, client: AsyncClient) -> None:
        """Archive containing a non-SQLite diarium.diarium gets 400."""
        archive = _make_archive_from_bytes(b"this is not sqlite data at all")
        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("bad.tar.gz", archive, "application/gzip")},
        )
        assert r.status_code == 400
        assert "not a valid SQLite" in r.json()["detail"]

    async def test_import_rejects_empty_db(self, client: AsyncClient) -> None:
        """Archive containing an empty diarium.diarium file gets 400."""
        archive = _make_archive_from_bytes(b"")
        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("empty.tar.gz", archive, "application/gzip")},
        )
        assert r.status_code == 400

    async def test_import_accepts_media_only_archive(
        self, client: AsyncClient
    ) -> None:
        """Archive with media/ but no database file imports just media."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"fake image data"
            info = tarfile.TarInfo(name="media/photo.jpg")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("media-only.tar.gz", buf.read(), "application/gzip")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "media" in data["restored"]

    async def test_import_accepts_legacy_dev_db_archive(
        self, client: AsyncClient, tmp_path: Path
    ) -> None:
        """Old archives using dev.db (instead of diarium.diarium) still import."""
        # Build an archive with a valid SQLite DB named "dev.db" (legacy format)
        db = _make_valid_db(tmp_path / "legacy.db")
        archive = _make_archive_from_bytes(db.read_bytes(), name="dev.db")

        # Patch init_db to avoid FTS setup errors with the minimal test schema
        async def _minimal_init_db():
            from app.core.database import Base, engine
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        with patch("app.core.database.init_db", side_effect=_minimal_init_db):
            r = await client.post(
                "/api/v1/backup/import",
                files={"file": ("legacy.tar.gz", archive, "application/gzip")},
            )
        # Should not get 400 — the import should accept the legacy name
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True


# ── Scheduler tests ──────────────────────────────────────────────────────────


class TestAutoBackupScheduler:
    """All tests clean up the global scheduler state in teardown."""

    async def test_schedule_backup(self, client: AsyncClient) -> None:
        backup_dir = tempfile.mkdtemp()
        try:
            r = await client.post(
                "/api/v1/backup/schedule",
                params={
                    "cron": "0 3 * * *",
                    "backup_path": backup_dir,
                    "retention": 5,
                },
            )
            assert r.status_code == 200
            data = r.json()
            assert data["job_id"] == "auto_backup"
            assert data["cron"] == "0 3 * * *"
            assert data["next_run"] is not None
        finally:
            await client.delete("/api/v1/backup/schedule")
            shutil.rmtree(backup_dir, ignore_errors=True)

    async def test_schedule_status_no_job(self, client: AsyncClient) -> None:
        await client.delete("/api/v1/backup/schedule")
        r = await client.get("/api/v1/backup/schedule/status")
        assert r.status_code == 200
        data = r.json()
        assert data["backup_scheduled"] is False

    async def test_schedule_status_with_job(self, client: AsyncClient) -> None:
        backup_dir = tempfile.mkdtemp()
        try:
            await client.post(
                "/api/v1/backup/schedule",
                params={
                    "cron": "30 1 * * *",
                    "backup_path": backup_dir,
                    "retention": 3,
                },
            )
            r = await client.get("/api/v1/backup/schedule/status")
            assert r.status_code == 200
            data = r.json()
            assert data["backup_scheduled"] is True
            assert data["next_run"] is not None
        finally:
            await client.delete("/api/v1/backup/schedule")
            shutil.rmtree(backup_dir, ignore_errors=True)

    async def test_unschedule_backup(self, client: AsyncClient) -> None:
        backup_dir = tempfile.mkdtemp()
        try:
            await client.post(
                "/api/v1/backup/schedule",
                params={
                    "cron": "0 0 * * *",
                    "backup_path": backup_dir,
                    "retention": 2,
                },
            )
            r = await client.delete("/api/v1/backup/schedule")
            assert r.status_code == 200
            assert r.json()["removed"] is True

            status = await client.get("/api/v1/backup/schedule/status")
            assert status.json()["backup_scheduled"] is False
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)

    async def test_schedule_replaces_existing(self, client: AsyncClient) -> None:
        backup_dir = tempfile.mkdtemp()
        try:
            await client.post(
                "/api/v1/backup/schedule",
                params={
                    "cron": "0 2 * * *",
                    "backup_path": backup_dir,
                    "retention": 5,
                },
            )
            r2 = await client.post(
                "/api/v1/backup/schedule",
                params={
                    "cron": "15 4 * * *",
                    "backup_path": backup_dir,
                    "retention": 3,
                },
            )
            assert r2.json()["cron"] == "15 4 * * *"
            status = await client.get("/api/v1/backup/schedule/status")
            assert status.json()["backup_scheduled"] is True
        finally:
            await client.delete("/api/v1/backup/schedule")
            shutil.rmtree(backup_dir, ignore_errors=True)

    async def test_schedule_rejects_invalid_cron(self, client: AsyncClient) -> None:
        backup_dir = tempfile.mkdtemp()
        try:
            # ValueError from SchedulerService propagates as server error
            with pytest.raises(ValueError, match="Invalid cron"):
                await client.post(
                    "/api/v1/backup/schedule",
                    params={
                        "cron": "not-a-cron",
                        "backup_path": backup_dir,
                        "retention": 5,
                    },
                )
        finally:
            await client.delete("/api/v1/backup/schedule")
            shutil.rmtree(backup_dir, ignore_errors=True)


# ── Scheduled backup execution ───────────────────────────────────────────────


class TestScheduledBackupExecution:
    async def test_run_backup_creates_archive(self, tmp_path: Path) -> None:
        """_run_backup produces a valid .tar.gz with diarium.diarium inside."""
        from app.services.scheduler_service import _run_backup

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_file = data_dir / "diarilinux.db"
        _make_valid_db(db_file)

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        import app.core.config as config_mod

        original_db_path = config_mod.settings.db_path
        original_media_dir = config_mod.settings.MEDIA_DIR
        original_db_url = config_mod.settings.DATABASE_URL

        config_mod.settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
        config_mod.settings.MEDIA_DIR = data_dir / "media"
        config_mod.settings.MEDIA_DIR.mkdir(exist_ok=True)

        try:
            await _run_backup(str(backup_dir), retention=5)
        finally:
            config_mod.settings.DATABASE_URL = original_db_url
            config_mod.settings.MEDIA_DIR = original_media_dir

        archives = list(backup_dir.glob("dailybyte-backup-*.tar.gz"))
        assert len(archives) == 1

        with tarfile.open(str(archives[0]), "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
            assert "diarium.diarium" in names

    def test_retention_cleanup(self, tmp_path: Path) -> None:
        """_cleanup_old_backups keeps only N most recent archives."""
        import time

        from app.services.scheduler_service import _cleanup_old_backups

        # Create 5 fake backup files with distinct mtimes
        for i in range(5):
            f = tmp_path / f"dailybyte-backup-2025010{i+1}-000000.tar.gz"
            f.write_bytes(f"backup-{i}".encode())
            # Ensure distinct mtime so sorting is deterministic
            os.utime(str(f), (1000 + i, 1000 + i))

        _cleanup_old_backups(tmp_path, retention=2)
        remaining = sorted(tmp_path.glob("dailybyte-backup-*.tar.gz"))
        assert len(remaining) == 2
        # Keeps the two newest (by mtime): 04 and 05
        assert remaining[0].name == "dailybyte-backup-20250104-000000.tar.gz"
        assert remaining[1].name == "dailybyte-backup-20250105-000000.tar.gz"
