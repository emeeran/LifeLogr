"""Progress reporting for backup & restore (DM3).

Pins the contract the UI polls:
  * archive builds report per-file (phase, done, total) — "database" then
    "media" — with monotonic done and a real total;
  * cloud backups report prepare → database/media → upload → retention →
    counts, and still complete;
  * cloud restores report lookup → download → extract → swap → counts;
  * the router's ``as_job`` wrapper really finishes/fails the job.
"""

from __future__ import annotations

import io
import tarfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jobs import jobs
from app.services.backup_service import BackupService

from tests.unit.test_backup_cloud_ops import _FakeProvider, _StreamingProvider, _make_config


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


class _Collector:
    """Records (phase, done, total) events; asserts monotonicity on read."""

    def __init__(self) -> None:
        self.events: list[tuple[str, int, int | None]] = []

    def __call__(self, phase: str, done: int = 0, total: int | None = None, detail=None) -> None:
        self.events.append((phase, done, total))

    @property
    def phases(self) -> list[str]:
        seen: list[str] = []
        for phase, _, _ in self.events:
            if not seen or seen[-1] != phase:
                seen.append(phase)
        return seen

    def assert_monotonic(self) -> None:
        last_done: dict[str, int] = {}
        for phase, done, total in self.events:
            # done resets when a new phase starts; within a phase it only climbs.
            assert done >= last_done.get(phase, 0)
            last_done[phase] = done
            if total is not None:
                assert done <= total


def _make_media_dir(tmp_path, count: int):
    media = tmp_path / "media"
    media.mkdir()
    for i in range(count):
        (media / f"img{i}.jpg").write_bytes(b"x" * 10)
    return media


# ── add_backup_members progress ──────────────────────────────────────────────


class TestArchiveProgress:
    def test_reports_database_then_media_per_file(self, tmp_path) -> None:
        from app.core.archive import add_backup_members

        db_file = tmp_path / "diarium.diarium"
        db_file.write_bytes(b"db")
        media = _make_media_dir(tmp_path, 3)
        collector = _Collector()

        with tarfile.open(tmp_path / "a.tar.gz", "w:gz") as tar:
            add_backup_members(tar, db_file, media, report=collector)

        collector.assert_monotonic()
        assert collector.phases == ["database", "media"]
        assert collector.events[-1] == ("media", 4, 4)  # 1 db + 3 media
        # The archive really contains everything, media nested under media/.
        with tarfile.open(tmp_path / "a.tar.gz") as tar:
            names = tar.getnames()
        assert names == [
            "diarium.diarium",
            "media/img0.jpg",
            "media/img1.jpg",
            "media/img2.jpg",
            "manifest.json",
        ]

    def test_empty_install_reports_a_single_zero_event(self, tmp_path) -> None:
        from app.core.archive import add_backup_members

        media = tmp_path / "media"
        media.mkdir()
        collector = _Collector()
        with tarfile.open(tmp_path / "a.tar.gz", "w:gz") as tar:
            add_backup_members(tar, tmp_path / "missing.db", media, report=collector)
        assert collector.events == [("archive", 0, 0)]

    def test_without_report_still_writes_every_member_and_manifest(self, tmp_path) -> None:
        """No reporter → same member set (per-file, hashed) plus the manifest."""
        from app.core.archive import add_backup_members

        db_file = tmp_path / "diarium.diarium"
        db_file.write_bytes(b"db")
        media = _make_media_dir(tmp_path, 2)
        with tarfile.open(tmp_path / "a.tar.gz", "w:gz") as tar:
            add_backup_members(tar, db_file, media)
        with tarfile.open(tmp_path / "a.tar.gz") as tar:
            names = tar.getnames()
        assert names[0] == "diarium.diarium"
        assert "media/img0.jpg" in names
        assert "media/img1.jpg" in names
        assert names[-1] == "manifest.json"


# ── cloud backup phases ──────────────────────────────────────────────────────


class TestRunBackupProgress:
    async def test_all_phases_reported_and_backup_completes(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ) -> None:
        config = await _make_config(db_session)
        fake = _FakeProvider([])

        # Point the archive build at throwaway paths.
        db_file = tmp_path / "diarium.diarium"
        db_file.write_bytes(b"db")
        media = _make_media_dir(tmp_path, 2)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
        monkeypatch.setattr(settings, "MEDIA_DIR", media)

        collector = _Collector()
        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake),
            patch("app.services.backup_service.cloud_backup_retention", lambda: 2),
        ):
            snapshot = await BackupService(db_session).run_backup(config.id, report=collector)

        assert snapshot.status == "completed"
        collector.assert_monotonic()
        assert collector.phases == ["prepare", "database", "media", "upload", "retention", "counts"]

    async def test_failed_backup_still_reports_through_upload(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ) -> None:
        config = await _make_config(db_session)
        fake = _FakeProvider([])
        fake.upload_file = AsyncMock(side_effect=RuntimeError("provider down"))

        db_file = tmp_path / "diarium.diarium"
        db_file.write_bytes(b"db")
        media = _make_media_dir(tmp_path, 0)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
        monkeypatch.setattr(settings, "MEDIA_DIR", media)

        collector = _Collector()
        with patch("app.services.cloud_sync_service.BoxProvider", return_value=fake):
            snapshot = await BackupService(db_session).run_backup(config.id, report=collector)

        assert snapshot.status == "failed"
        assert "provider down" in snapshot.error_message
        assert "upload" in collector.phases
        assert "counts" not in collector.phases


# ── cloud restore phases ─────────────────────────────────────────────────────


class TestRestoreProgress:
    async def test_all_phases_reported(self, db_session: AsyncSession) -> None:
        config = await _make_config(db_session)
        fake = _StreamingProvider(["lifelogr-backup-1.tar.gz"], payload=_archive_bytes())
        collector = _Collector()

        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake),
            patch(
                "app.core.restore.atomic_restore",
                AsyncMock(return_value=["database", "media"]),
            ),
        ):
            result = await BackupService(db_session).restore(config.id, report=collector)

        assert result == {"entries_restored": 0, "media_restored": 0}
        collector.assert_monotonic()
        assert collector.phases == [
            "lookup",
            "download",
            "verify",
            "extract",
            "swap",
            "counts",
        ]
        assert fake.downloaded == ["lifelogr-backup-1.tar.gz"]


def _archive_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="diarium.diarium")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"db--"))
    return buf.getvalue()


# ── router as_job wrapper ────────────────────────────────────────────────────


class TestStartDataJob:
    async def test_job_runs_to_done_with_detail(self) -> None:
        from app.routers.backup import _start_data_job

        async def runner(report) -> str:
            report("working", 1, 1)
            return "all set"

        tasks = BackgroundTasks()
        body = _start_data_job(tasks, "backup", runner)
        await tasks()  # starlette runs background tasks when called

        job = jobs.get(body["job_id"])
        assert body["kind"] == "backup"
        assert job is not None
        assert job.status == "done"
        assert job.detail == "all set"

    async def test_job_failure_lands_on_the_job(self) -> None:
        from app.routers.backup import _start_data_job

        async def runner(report) -> str:
            raise RuntimeError("disk full")

        tasks = BackgroundTasks()
        body = _start_data_job(tasks, "restore", runner)
        await tasks()

        job = jobs.get(body["job_id"])
        assert job is not None
        assert job.status == "failed"
        assert job.error == "disk full"
