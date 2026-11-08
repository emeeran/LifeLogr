"""Trash semantics: soft delete keeps media (restorable), purge destroys it.

Regression guard for the 2026-11-08 audit blocker: soft delete used to
hard-delete every media file at trash time, so a "recoverable" delete
permanently destroyed photos and voice recordings while the notes flow was
lossless. Delete must now keep attachments until an explicit purge (or the
daily retention sweep).
"""

import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media import Media
from app.services.entry_service import EntryService


def _png_bytes() -> bytes:
    """A real PNG — the hand-made 1×1 stub trips exif_transpose in Pillow."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (30, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def _entry_with_media(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[dict, dict, Path]:
    r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "x"})
    assert r.status_code == 201
    entry = r.json()
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry["id"])},
        files={"file": ("pic.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201
    media = r.json()
    # The API response doesn't expose storage_path; read it from the row.
    row = (
        await db_session.execute(select(Media).where(Media.id == media["id"]))
    ).scalar_one()
    media_path = Path(settings.MEDIA_DIR / row.storage_path)
    assert media_path.exists()
    return entry, media, media_path


class TestSoftDeleteKeepsMedia:
    async def test_soft_delete_keeps_media_file_and_row(self, client: AsyncClient, db_session: AsyncSession):
        entry, media, media_path = await _entry_with_media(client, db_session)
        r = await client.delete(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 204
        assert media_path.exists(), "trash must not destroy the attachment"

    async def test_restore_recovers_entry_and_media(self, client: AsyncClient, db_session: AsyncSession):
        entry, media, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.post(f"/api/v1/entries/{entry['id']}/restore")
        assert r.status_code == 200
        assert r.json()["is_deleted"] is False
        assert media_path.exists()

        r = await client.get(f"/api/v1/media/{media['id']}/file")
        assert r.status_code == 200


class TestPurge:
    async def test_purge_removes_entry_media_row_and_file(self, client: AsyncClient, db_session: AsyncSession):
        entry, media, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.delete(f"/api/v1/entries/{entry['id']}/purge")
        assert r.status_code == 204

        assert not media_path.exists(), "purge is the step that destroys the file"
        remaining = await db_session.execute(select(Media).where(Media.id == media["id"]))
        assert remaining.scalar_one_or_none() is None
        r = await client.get(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 404

    async def test_purge_live_entry_directly(self, client: AsyncClient, db_session: AsyncSession):
        entry, _, media_path = await _entry_with_media(client, db_session)
        r = await client.delete(f"/api/v1/entries/{entry['id']}/purge")
        assert r.status_code == 204
        assert not media_path.exists()

    async def test_purge_missing_returns_404(self, client: AsyncClient):
        r = await client.delete("/api/v1/entries/99999/purge")
        assert r.status_code == 404


class TestRetentionSweep:
    async def _backdate(self, db_session: AsyncSession, entry_id: int, days: int) -> None:
        from app.models.entry import Entry

        entry = (await db_session.execute(select(Entry).where(Entry.id == entry_id))).scalar_one()
        entry.deleted_at = datetime.now(timezone.utc) - timedelta(days=days)
        await db_session.commit()

    async def test_expired_trash_is_purged(self, client: AsyncClient, db_session: AsyncSession):
        entry, media, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")
        await self._backdate(db_session, entry["id"], settings.TRASH_RETENTION_DAYS + 1)

        purged = await EntryService(db_session).purge_expired_trash()
        assert purged == 1
        assert not media_path.exists()

    async def test_recent_trash_survives(self, client: AsyncClient, db_session: AsyncSession):
        entry, _, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")
        await self._backdate(db_session, entry["id"], 1)

        purged = await EntryService(db_session).purge_expired_trash()
        assert purged == 0
        assert media_path.exists()

    async def test_zero_retention_disables_sweep(self, client: AsyncClient, db_session: AsyncSession):
        entry, _, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")
        await self._backdate(db_session, entry["id"], 10_000)

        with unittest.mock.patch.object(settings, "TRASH_RETENTION_DAYS", 0):
            purged = await EntryService(db_session).purge_expired_trash()
        assert purged == 0
        assert media_path.exists()
