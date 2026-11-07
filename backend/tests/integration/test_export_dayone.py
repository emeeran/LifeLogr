"""Day One ZIP export — the push half of a file-based Diarium sync.

Diarium imports this format via Settings → Migrate from other app → Day One and
resolves attachments by the ``md5`` in the JSON matching archive filenames, so
the shape asserted here (md5-named members, noon-UTC creationDate, photos[]
entries) is the contract.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.models.tag import EntryTag, Tag
from app.services.importers import parse_dayone_zip

PHOTO = b"\xff\xd8\xff\xe0dayone-photo"


def _media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    (root / "images").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "MEDIA_DIR", root)
    return root


async def _seed_entry(
    db_session,
    *,
    day: date,
    body: str = "Body text",
    title: str | None = None,
    external_id: str | None = None,
    encrypted: bool = False,
    media: bytes | None = None,
    root=None,
) -> Entry:
    from app.models.media import Media as MediaRow

    entry = Entry(
        entry_date=day,
        title=title,
        body=body,
        latitude=45.5 if media else None,
        longitude=-122.6 if media else None,
        location_name="Lake" if media else None,
        external_source="diarium" if external_id else None,
        external_id=external_id,
        is_encrypted=encrypted,
    )
    db_session.add(entry)
    await db_session.flush()

    tag = Tag(name=f"tag-{entry.id}")
    db_session.add(tag)
    await db_session.flush()
    db_session.add(EntryTag(entry_id=entry.id, tag_id=tag.id))

    if media is not None and root is not None:
        name = f"{day.isoformat()}.jpg"
        (root / "images" / name).write_bytes(media)
        db_session.add(
            MediaRow(
                entry_id=entry.id,
                filename="photo.jpg",
                media_type="image",
                file_size=len(media),
                storage_path=f"images/{name}",
                caption="A lake",
                is_inline=False,
            )
        )
    await db_session.commit()
    return entry


def _read_zip(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    return json.loads(zipfile.ZipFile(io.BytesIO(data)).read("Journal.json")), zipfile.ZipFile(
        io.BytesIO(data)
    )


async def test_dayone_zip_shape_and_round_trip(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    root = _media_root(tmp_path, monkeypatch)
    entry = await _seed_entry(
        db_session,
        day=date(2026, 2, 3),
        body="A day at the lake.",
        title="Lake day",
        media=PHOTO,
        root=root,
    )

    r = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    doc, zf = _read_zip(r.content)
    assert doc["metadata"]["generator"] == "LifeLogr"
    assert len(doc["entries"]) == 1
    item = doc["entries"][0]

    digest = hashlib.md5(PHOTO, usedforsecurity=False).hexdigest()
    assert item["text"] == "A day at the lake."
    assert item["title"] == "Lake day"
    assert item["creationDate"] == "2026-02-03T12:00:00Z"
    assert item["tags"] == [f"tag-{entry.id}"]
    assert item["location"]["latitude"] == 45.5
    assert item["photos"] == [
        {
            "identifier": f"{digest}.jpg",
            "md5": digest,
            "type": "jpeg",
            "filename": f"{digest}.jpg",
            "size": len(PHOTO),
            "caption": "A lake",
        }
    ]
    # Diarium resolves the attachment by the md5 prefix in the member name.
    assert zf.read(f"photos/{digest}.jpg") == PHOTO

    # Our own Day One importer understands the file, so the format is honest.
    parsed = parse_dayone_zip(r.content)
    assert len(parsed) == 1
    assert parsed[0]["body"] == "A day at the lake."
    assert parsed[0]["title"] == "Lake day"
    assert parsed[0]["entry_date"] == "2026-02-03"
    assert parsed[0]["tags"] == [f"tag-{entry.id}"]
    assert parsed[0]["media"][0]["data"] == PHOTO


async def test_scope_new_skips_diarium_entries_and_covered_days(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    await _seed_entry(  # came from Diarium
        db_session, day=date(2026, 1, 1), body="From Diarium", external_id="639000000000000000"
    )
    await _seed_entry(  # authored here, but Diarium already has that day
        db_session, day=date(2026, 1, 1), body="Same day, local"
    )
    await _seed_entry(db_session, day=date(2026, 1, 2), body="Brand new day")

    new = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "new"})
    doc, _ = _read_zip(new.content)
    assert [e["text"] for e in doc["entries"]] == ["Brand new day"]

    everything = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})
    doc_all, _ = _read_zip(everything.content)
    assert sorted(e["text"] for e in doc_all["entries"]) == [
        "Brand new day",
        "From Diarium",
        "Same day, local",
    ]


async def test_encrypted_entries_are_skipped_and_counted(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    await _seed_entry(
        db_session, day=date(2026, 3, 1), body="ciphertext-blob", encrypted=True
    )

    r = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})
    doc, _ = _read_zip(r.content)
    assert doc["entries"] == []
    assert doc["metadata"]["skipped_encrypted"] == 1


async def test_uuid_is_stable_across_exports(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    entry = await _seed_entry(db_session, day=date(2026, 4, 1), body="Stable")
    assert entry.id

    first, _ = _read_zip(
        (await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})).content
    )
    second, _ = _read_zip(
        (await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})).content
    )
    assert first["entries"][0]["uuid"] == second["entries"][0]["uuid"]


async def test_unknown_scope_is_rejected(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    r = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "nope"})
    assert r.status_code == 400


async def test_missing_media_file_is_skipped_not_fatal(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    root = _media_root(tmp_path, monkeypatch)
    await _seed_entry(
        db_session, day=date(2026, 5, 1), body="Photo vanished", media=PHOTO, root=root
    )
    rows = (await db_session.execute(select(Media))).scalars().all()
    (root / rows[0].storage_path).unlink()

    r = await client.get("/api/v1/entries/export/dayone-zip", params={"scope": "all"})
    assert r.status_code == 200
    doc, _ = _read_zip(r.content)
    assert len(doc["entries"]) == 1
    assert "photos" not in doc["entries"][0]
