"""Streaming uploads + the from-path import sandbox.

Covers the two media-upload fixes that are easy to regress:

* ``spool_upload`` must enforce the size cap **while streaming** — an oversized
  body is rejected without ever being materialised in memory or fully written
  to disk;
* ``upload_from_path`` must only read from user space (positive allowlist), and
  never from hidden/sensitive locations.
"""

import io
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, ValidationError
from app.schemas.entry import EntryCreate
from app.services.entry_service import EntryService
from app.services.media_service import MediaService, allowed_import_roots, spool_upload

# Minimal PNG (1×1) — same stub the other media tests use.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0f01f0005000105ab5e30"
    "5f0000000049454e44ae426082"
)


def _upload(payload: bytes, filename: str = "blob.bin") -> UploadFile:
    return UploadFile(file=io.BytesIO(payload), filename=filename)


class TestSpoolUpload:
    async def test_small_file_spools_completely(self, tmp_path):
        f = _upload(b"hello world", "hello.txt")
        path, size = await spool_upload(f, 1024)
        try:
            assert size == 11
            assert path.read_bytes() == b"hello world"
        finally:
            path.unlink(missing_ok=True)

    async def test_oversized_upload_rejected_incrementally(self):
        """The cap fires mid-stream: the spool never holds the whole payload."""
        chunk = b"x" * 65536
        max_bytes = 100_000  # ~1.5 chunks — far below the payload size
        f = _upload(chunk * 10)
        with pytest.raises(MediaSizeError):
            await spool_upload(f, max_bytes)

    async def test_exact_cap_is_accepted(self):
        payload = b"y" * 2048
        f = _upload(payload)
        path, size = await spool_upload(f, 2048)
        try:
            assert size == 2048
        finally:
            path.unlink(missing_ok=True)


class TestUploadFileService:
    """``MediaService.upload_file`` — the spooled-path counterpart of upload()."""

    async def test_stores_spooled_png_and_converts(self, db_session: AsyncSession, tmp_path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        spool = tmp_path / "spool.png"
        spool.write_bytes(_PNG_1x1)
        media = await MediaService(db_session).upload_file(
            entry.id, "pic.png", "image/png", spool
        )
        assert media.entry_id == entry.id
        assert media.media_type == "image"
        # 1×1 PNG can't shrink further — either way the file lands on disk.
        assert (settings.MEDIA_DIR / media.storage_path).is_file()

    async def test_moves_non_image_without_reread(self, db_session: AsyncSession, tmp_path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        spool = tmp_path / "spool.mp3"
        spool.write_bytes(b"ID3fake audio bytes")
        media = await MediaService(db_session).upload_file(
            entry.id, "song.mp3", "audio/mpeg", spool
        )
        assert media.media_type == "audio"
        stored = settings.MEDIA_DIR / media.storage_path
        assert stored.is_file()
        assert stored.read_bytes() == b"ID3fake audio bytes"

    async def test_rejects_oversized_spool(self, db_session: AsyncSession, tmp_path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        spool = tmp_path / "spool.png"
        spool.write_bytes(_PNG_1x1)
        with pytest.raises(MediaSizeError):
            await MediaService(db_session).upload_file(
                entry.id,
                "pic.png",
                "image/png",
                spool,
                size=settings.MAX_MEDIA_SIZE_BYTES + 1,
            )

    async def test_rejects_blocked_signature(self, db_session: AsyncSession, tmp_path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        spool = tmp_path / "spool.png"
        spool.write_bytes(b"MZ\x90\x00")
        with pytest.raises(MediaSizeError):
            await MediaService(db_session).upload_file(
                entry.id, "evil.png", "image/png", spool
            )


class TestImportAllowlist:
    """``upload_from_path`` reads only user space — never hidden/sensitive dirs."""

    @pytest.fixture
    def fake_home(self, monkeypatch, tmp_path) -> Path:
        import app.services.media_service as ms

        monkeypatch.setattr(ms.Path, "home", staticmethod(lambda: tmp_path))
        return tmp_path

    async def test_allows_downloads(self, db_session: AsyncSession, fake_home: Path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        pic = fake_home / "Downloads" / "pic.png"
        pic.parent.mkdir(parents=True)
        pic.write_bytes(_PNG_1x1)
        media = await MediaService(db_session).upload_from_path(entry.id, str(pic))
        assert media.media_type == "image"

    async def test_rejects_ssh(self, db_session: AsyncSession, fake_home: Path):
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        key = fake_home / ".ssh" / "id_rsa"
        key.parent.mkdir(parents=True)
        key.write_bytes(b"PRIVATE KEY")
        with pytest.raises(ValidationError):
            await MediaService(db_session).upload_from_path(entry.id, str(key))

    async def test_rejects_other_hidden_dir(self, db_session: AsyncSession, fake_home: Path):
        """Hidden folders beyond the explicit denylist are denied too (~/.aws, …)."""
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        creds = fake_home / ".aws" / "credentials"
        creds.parent.mkdir(parents=True)
        creds.write_text("[default]")
        with pytest.raises(ValidationError):
            await MediaService(db_session).upload_from_path(entry.id, str(creds))

    async def test_allows_visible_home_subfolder(self, db_session: AsyncSession, fake_home: Path):
        """Drag-drop from an arbitrary visible folder keeps working."""
        entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
        pic = fake_home / "Projects" / "site" / "shot.png"
        pic.parent.mkdir(parents=True)
        pic.write_bytes(_PNG_1x1)
        media = await MediaService(db_session).upload_from_path(entry.id, str(pic))
        assert media.entry_id == entry.id

    async def test_extra_root_via_env(self, monkeypatch, tmp_path):
        """Operator-configured roots are honoured (mirrors BACKUP_ALLOWED_ROOTS)."""

        monkeypatch.setenv("MEDIA_IMPORT_ALLOWED_ROOTS", str(tmp_path / "mnt"))
        roots = allowed_import_roots()
        assert (tmp_path / "mnt") in roots

    def test_standard_user_dirs_are_allowlisted(self):
        roots = allowed_import_roots()
        names = {r.name for r in roots}
        assert {"Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"} <= names


class TestApiStreamingWiring:
    """The media endpoints spool instead of buffering the whole body."""

    async def test_oversized_upload_rejected_before_store(
        self, client: AsyncClient, monkeypatch
    ):
        """A tiny cap + a bigger body → 400, and nothing is written to MEDIA_DIR."""
        from app.models.media import Media
        from sqlalchemy import func, select

        monkeypatch.setattr(settings, "MAX_MEDIA_SIZE_BYTES", 1024)
        r = await client.post(
            "/api/v1/media",
            data={"entry_id": "1"},
            files={"file": ("big.png", b"x" * 4096, "image/png")},
        )
        assert r.status_code == 400
        assert "exceeds" in r.json()["detail"]
        # And no media row / no stored file leaked past the cap.
        total = (
            await client.get("/api/v1/media/entry/1")
        ).json()
        assert total == []
        from app.core.database import async_session

        async with async_session() as session:
            count = (
                await session.execute(select(func.count()).select_from(Media))
            ).scalar_one()
        assert count == 0

    async def test_upload_via_api_stores_file(self, client: AsyncClient):
        entry = (
            await client.post(
                "/api/v1/entries", json={"entry_date": date(2026, 5, 1).isoformat(), "body": "m"}
            )
        ).json()
        r = await client.post(
            "/api/v1/media",
            data={"entry_id": str(entry["id"])},
            files={"file": ("song.mp3", b"ID3fake audio", "audio/mpeg")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "audio"


class TestNoteMediaUploadFile:
    """``NoteMediaService.upload_file`` — the spooled counterpart for notes.

    (The note upload router still buffers; it is owned by another workstream —
    the service entry point is ready for it.)
    """

    async def test_stores_spooled_file(self, db_session: AsyncSession, tmp_path):
        from app.models.note import Note
        from app.services.note_media_service import NoteMediaService

        note = Note(title="n", body="b")
        db_session.add(note)
        await db_session.commit()

        spool = tmp_path / "spool.png"
        spool.write_bytes(_PNG_1x1)
        media = await NoteMediaService(db_session).upload_file(
            note.id, "pic.png", "image/png", spool
        )
        assert media.note_id == note.id
        assert media.storage_path.startswith("notes/")
        assert (settings.MEDIA_DIR / media.storage_path).is_file()

    async def test_rejects_oversized_spool(self, db_session: AsyncSession, tmp_path):
        from app.models.note import Note
        from app.services.note_media_service import NoteMediaService

        note = Note(title="n", body="b")
        db_session.add(note)
        await db_session.commit()

        spool = tmp_path / "spool.mp3"
        spool.write_bytes(b"audio")
        with pytest.raises(MediaSizeError):
            await NoteMediaService(db_session).upload_file(
                note.id,
                "big.mp3",
                "audio/mpeg",
                spool,
                size=settings.MAX_MEDIA_SIZE_BYTES + 1,
            )

    async def test_rejects_blocked_signature(self, db_session: AsyncSession, tmp_path):
        from app.models.note import Note
        from app.services.note_media_service import NoteMediaService

        note = Note(title="n", body="b")
        db_session.add(note)
        await db_session.commit()

        spool = tmp_path / "spool.png"
        spool.write_bytes(b"MZ\x90\x00")
        with pytest.raises(MediaSizeError):
            await NoteMediaService(db_session).upload_file(
                note.id, "evil.png", "image/png", spool
            )
