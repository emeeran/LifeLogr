"""End-to-end import of the golden Day One export ZIP (photos + text + tags)."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.models.tag import EntryTag, Tag

GOLDEN = Path(__file__).parent.parent / "golden" / "dayone_export.zip"


async def test_import_dayone_zip_with_photos_end_to_end(client: AsyncClient, db_session) -> None:
    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("dayone_export.zip", GOLDEN.read_bytes(), "application/zip")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 3, body["skip_reasons"]

    rows = (
        (await db_session.execute(select(Entry).order_by(Entry.entry_date)))
        .scalars()
        .all()
    )
    assert [str(e.entry_date) for e in rows] == ["2024-02-01", "2024-02-02", "2024-02-03"]

    # Text + photo entry: tag and location preserved.
    first = rows[0]
    assert first.title == "Ridge hike"
    assert first.latitude == 45.5 and first.longitude == -122.6
    tag_names = (
        await db_session.execute(
            select(Tag.name).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == first.id)
        )
    ).scalars().all()
    assert tag_names == ["hiking"]

    # Photo-only entry: empty body, one attached image on disk.
    photo_only = rows[1]
    assert photo_only.body == ""
    media = (
        (await db_session.execute(select(Media).where(Media.entry_id == photo_only.id)))
        .scalars()
        .all()
    )
    assert len(media) == 1
    assert media[0].media_type == "image"
    stored = Path(settings.MEDIA_DIR) / media[0].storage_path
    assert stored.is_file()
    # The text+photo entry carries the same image.
    first_media = (
        (await db_session.execute(select(Media).where(Media.entry_id == first.id)))
        .scalars()
        .all()
    )
    assert len(first_media) == 1

    detail = (await client.get(f"/api/v1/entries/{first.id}")).json()
    assert detail["media_count"] == 1


async def test_import_dayone_zip_dedup_skips_second_run(client: AsyncClient, db_session) -> None:
    for expected_imported in (3, 0):
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("dayone_export.zip", GOLDEN.read_bytes(), "application/zip")},
        )
        assert r.status_code == 200
        assert r.json()["imported"] == expected_imported
