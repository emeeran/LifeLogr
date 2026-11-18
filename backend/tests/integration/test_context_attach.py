"""A listed context photo must land in the normal media pipeline when attached."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.media import Media
from tests.helpers.dayone_zip import PNG_1X1


async def test_attached_photo_lands_in_media_pipeline(client: AsyncClient, db_session, tmp_path) -> None:
    d = tmp_path / "roll"
    d.mkdir()
    photo = d / "shot.png"
    photo.write_bytes(PNG_1X1)

    listed = await client.post("/api/v1/context/photos", json={"path": str(d)})
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["path"] == str(photo)

    entry = (
        await client.post("/api/v1/entries", json={"entry_date": "2026-10-25", "body": "With photo."})
    ).json()
    attached = await client.post(
        "/api/v1/media/from-path",
        json={"entry_id": entry["id"], "path": item["path"]},
    )
    assert attached.status_code == 201, attached.text

    media = (
        (await db_session.execute(select(Media).where(Media.entry_id == entry["id"])))
        .scalars()
        .all()
    )
    assert len(media) == 1
    assert media[0].media_type == "image"
    assert (Path(settings.MEDIA_DIR) / media[0].storage_path).is_file()
