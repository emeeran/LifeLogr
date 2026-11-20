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


async def _create_entry(client: AsyncClient, body: str) -> dict:
    r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": body})
    assert r.status_code == 201
    return r.json()


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
    row = (await db_session.execute(select(Media).where(Media.id == media["id"]))).scalar_one()
    media_path = Path(settings.MEDIA_DIR / row.storage_path)
    assert media_path.exists()
    return entry, media, media_path


class TestSoftDeleteKeepsMedia:
    async def test_soft_delete_keeps_media_file_and_row(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entry, media, media_path = await _entry_with_media(client, db_session)
        r = await client.delete(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 204
        assert media_path.exists(), "trash must not destroy the attachment"

    async def test_restore_recovers_entry_and_media(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entry, media, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.post(f"/api/v1/entries/{entry['id']}/restore")
        assert r.status_code == 200
        assert r.json()["is_deleted"] is False
        assert media_path.exists()

        r = await client.get(f"/api/v1/media/{media['id']}/file")
        assert r.status_code == 200


class TestPurge:
    async def test_purge_removes_entry_media_row_and_file(
        self, client: AsyncClient, db_session: AsyncSession
    ):
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


class TestEmptyTrash:
    # Production DBs created these three tables before the models gained
    # ondelete=CASCADE, and inline migrations only add columns — never rebuild
    # tables — so the live FKs have no CASCADE clause. The set-based bulk
    # deletes (empty trash, retention sweep) are DB-level and must therefore
    # not rely on the database to cascade into these children.
    _LEGACY_DDL = [
        """CREATE TABLE media (
	id INTEGER NOT NULL,
	entry_id INTEGER NOT NULL,
	filename VARCHAR NOT NULL,
	media_type VARCHAR NOT NULL,
	file_size INTEGER NOT NULL,
	storage_path VARCHAR NOT NULL,
	caption VARCHAR(500),
	is_inline BOOLEAN NOT NULL,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT max_media_size CHECK (file_size <= 26214400),
	FOREIGN KEY(entry_id) REFERENCES entries (id)
)""",
        "CREATE INDEX ix_media_entry_id ON media (entry_id)",
        """CREATE TABLE entry_tags (
	entry_id INTEGER NOT NULL,
	tag_id INTEGER NOT NULL, tracking_value VARCHAR(500),
	PRIMARY KEY (entry_id, tag_id),
	UNIQUE (entry_id, tag_id),
	FOREIGN KEY(entry_id) REFERENCES entries (id),
	FOREIGN KEY(tag_id) REFERENCES tags (id)
)""",
        "CREATE INDEX ix_entry_tags_tag_id ON entry_tags (tag_id)",
        """CREATE TABLE voice_recordings (
	id INTEGER NOT NULL,
	entry_id INTEGER NOT NULL,
	media_id INTEGER NOT NULL,
	duration_seconds FLOAT NOT NULL,
	audio_format VARCHAR(10) NOT NULL,
	transcription VARCHAR,
	is_transcribed BOOLEAN NOT NULL,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(entry_id) REFERENCES entries (id),
	FOREIGN KEY(media_id) REFERENCES media (id)
)""",
        "CREATE INDEX ix_voice_recordings_entry_id ON voice_recordings (entry_id)",
        "CREATE INDEX ix_voice_recordings_media_id ON voice_recordings (media_id)",
    ]

    async def _rebuild_legacy_tables(self, db_session: AsyncSession) -> None:
        """Swap in the production (pre-CASCADE) shape of the child tables.

        Mirrors the DDL verbatim from a production DB; must run before any
        rows exist so the drops can't violate the FKs they replace.
        """
        from sqlalchemy import text

        for table in ("voice_recordings", "entry_tags", "media"):
            await db_session.execute(text(f"DROP TABLE {table}"))
        for ddl in self._LEGACY_DDL:
            await db_session.execute(text(ddl))
        await db_session.commit()

    async def test_empty_trash_survives_pre_cascade_schema(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await self._rebuild_legacy_tables(db_session)
        entry, media, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.delete("/api/v1/entries/trash")
        assert r.status_code == 200, "bulk purge must not hit the un-cascaded FKs"
        assert r.json() == {"purged": 1}
        assert not media_path.exists()

    async def test_single_purge_survives_pre_cascade_schema(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """DELETE /entries/{id}/purge against the production (pre-CASCADE) DDL.

        Regression: purge relied on CASCADE for media/voice_recordings, which
        the production tables don't carry — the endpoint 500'd with
        "FOREIGN KEY constraint failed" and the entry stayed stuck in trash
        until the daily sweep (found by the 2026-11-20 blind review)."""
        await self._rebuild_legacy_tables(db_session)
        entry, media, media_path = await _entry_with_media(client, db_session)

        r = await client.delete(f"/api/v1/entries/{entry['id']}/purge")
        assert r.status_code == 204, "single purge must not hit the un-cascaded FKs"
        assert not media_path.exists()

    async def test_empty_trash_purges_deleted_keeps_live(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entry, media, media_path = await _entry_with_media(client, db_session)
        live = await _create_entry(client, "still here")
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.delete("/api/v1/entries/trash")
        assert r.status_code == 200
        assert r.json() == {"purged": 1}

        assert not media_path.exists(), "emptying trash destroys the attachment"
        await db_session.rollback()  # drop the pre-delete snapshot
        remaining = await db_session.execute(select(Media).where(Media.id == media["id"]))
        assert remaining.scalar_one_or_none() is None
        assert (await client.get(f"/api/v1/entries/{entry['id']}")).status_code == 404
        assert (await client.get(f"/api/v1/entries/{live['id']}")).status_code == 200

        # The trash list is empty afterwards.
        r = await client.get("/api/v1/entries/trash")
        assert r.json()["total"] == 0

    async def test_empty_trash_on_empty_trash_returns_zero(self, client: AsyncClient):
        r = await client.delete("/api/v1/entries/trash")
        assert r.status_code == 200
        assert r.json() == {"purged": 0}

    async def test_a_hostile_origin_cannot_empty_trash(self, client: AsyncClient):
        """The route sits behind the destructive-origin guard like the purge."""
        r = await client.delete(
            "/api/v1/entries/trash", headers={"Origin": "http://127.0.0.1:9999"}
        )
        assert r.status_code == 403


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

    async def test_zero_retention_disables_sweep(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entry, _, media_path = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")
        await self._backdate(db_session, entry["id"], 10_000)

        with unittest.mock.patch.object(settings, "TRASH_RETENTION_DAYS", 0):
            purged = await EntryService(db_session).purge_expired_trash()
        assert purged == 0
        assert media_path.exists()


class TestTrashListing:
    """GET /entries/trash — the listing behind the frontend trash view."""

    async def test_lists_only_deleted_entries(self, client: AsyncClient, db_session: AsyncSession):
        kept = await _create_entry(client, body="kept")
        entry, _, _ = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")

        r = await client.get("/api/v1/entries/trash")
        assert r.status_code == 200
        items = r.json()["items"]
        assert [i["id"] for i in items] == [entry["id"]]
        assert kept["id"] not in [i["id"] for i in items]
        assert items[0]["deleted_at"] is not None
        assert items[0]["body_snippet"] == "x"
        assert items[0]["media_count"] == 1

    async def test_ordered_by_deleted_at_desc(self, client: AsyncClient, db_session: AsyncSession):
        from app.models.entry import Entry

        first = await _create_entry(client, body="first")
        second = await _create_entry(client, body="second")
        await client.delete(f"/api/v1/entries/{first['id']}")
        await client.delete(f"/api/v1/entries/{second['id']}")
        # Make the first deletion strictly older.
        row = (await db_session.execute(select(Entry).where(Entry.id == first["id"]))).scalar_one()
        row.deleted_at -= timedelta(seconds=5)
        await db_session.commit()

        r = await client.get("/api/v1/entries/trash")
        assert [i["id"] for i in r.json()["items"]] == [second["id"], first["id"]]

    async def test_encrypted_entry_has_empty_snippet(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_entry(client, body="secret plan")
        from app.models.entry import Entry

        row = (await db_session.execute(select(Entry))).scalar_one()
        row.is_encrypted = True
        await db_session.commit()
        await client.delete(f"/api/v1/entries/{row.id}")

        items = (await client.get("/api/v1/entries/trash")).json()["items"]
        assert items[0]["is_encrypted"] is True
        assert items[0]["body_snippet"] == ""

    async def test_restore_removes_from_trash(self, client: AsyncClient, db_session: AsyncSession):
        entry, _, _ = await _entry_with_media(client, db_session)
        await client.delete(f"/api/v1/entries/{entry['id']}")
        await client.post(f"/api/v1/entries/{entry['id']}/restore")
        r = await client.get("/api/v1/entries/trash")
        assert r.json()["items"] == []

    async def test_pagination(self, client: AsyncClient, db_session: AsyncSession):
        from app.models.entry import Entry

        ids = [await _create_entry(client, body=f"e{i}") for i in range(3)]
        for i, e in enumerate(ids):
            await client.delete(f"/api/v1/entries/{e['id']}")
            # Distinct, ordered deletions: e0 oldest, e2 newest.
            row = (await db_session.execute(select(Entry).where(Entry.id == e["id"]))).scalar_one()
            row.deleted_at = datetime.now(timezone.utc) - timedelta(minutes=3 - i)
            await db_session.commit()

        r = await client.get("/api/v1/entries/trash?offset=1&limit=1")
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 1
        assert body["items"][0]["body_snippet"] == "e1"
