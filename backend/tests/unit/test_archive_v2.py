"""DM9 — native archive v2: notes + note attachments + events ride along.

v2 export → wipe → import reproduces entries, media, events, notes and note
attachments; a v1-shaped fixture (no notes/events keys) still imports.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.core.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def media_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "media"
    d.mkdir()
    monkeypatch.setattr(settings, "MEDIA_DIR", d)
    return d


async def _seed(db_session, media_dir: Path) -> None:
    from app.models.entry import Entry
    from app.models.entry_event import EntryEvent
    from app.models.media import Media
    from app.models.note import Note
    from app.models.note_media import NoteMedia
    from app.models.tag import EntryTag, Tag

    photo = b"\xff\xd8\xff\xe0jpeg-bytes"
    receipt = b"%PDF-1.7 pdf-bytes"

    entry = Entry(
        entry_date=date(2026, 6, 1),
        title="V2 entry",
        body="placeholder",
        mood="good",
    )
    db_session.add(entry)
    await db_session.flush()
    tag = Tag(name="tag-a")
    db_session.add(tag)
    media_row = Media(
        entry_id=entry.id,
        filename="photo.jpg",
        media_type="image",
        file_size=len(photo),
        storage_path="2026/06/photo.jpg",
    )
    db_session.add(media_row)
    note = Note(title="V2 note", body="placeholder")
    db_session.add(note)
    await db_session.flush()
    note_media = NoteMedia(
        note_id=note.id,
        filename="receipt.pdf",
        media_type="document",
        file_size=len(receipt),
        storage_path="notes/receipt.pdf",
    )
    db_session.add(note_media)
    await db_session.flush()
    # Bodies reference the export-time ids the archive records as `ref`.
    entry.body = f"Body with ![img](/api/v1/media/{media_row.id}/file) ref."
    note.body = f"Note ![r](/api/v1/notes/{note.id}/media/{note_media.id}/file) ref."
    db_session.add_all(
        [
            EntryTag(entry_id=entry.id, tag_id=tag.id),
            EntryEvent(entry_id=entry.id, kind="weather", content="72 / 55 °F", label="Clear"),
        ]
    )
    await db_session.commit()

    (media_dir / "2026" / "06").mkdir(parents=True, exist_ok=True)
    (media_dir / "2026" / "06" / "photo.jpg").write_bytes(photo)
    (media_dir / "notes").mkdir(parents=True, exist_ok=True)
    (media_dir / "notes" / "receipt.pdf").write_bytes(receipt)


async def _wipe(db_session, media_dir: Path) -> None:
    from app.models.entry import Entry
    from app.models.entry_event import EntryEvent
    from app.models.media import Media
    from app.models.note import Note
    from app.models.note_media import NoteMedia
    from app.models.tag import EntryTag, Tag

    for model in (NoteMedia, Note, EntryEvent, Media, EntryTag, Tag, Entry):
        await db_session.execute(delete(model))
    await db_session.commit()
    import shutil

    for child in media_dir.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()


async def test_archive_v2_roundtrip(db_session, client, media_dir):
    await _seed(db_session, media_dir)

    r = await client.get("/api/v1/entries/export/archive")
    assert r.status_code == 200
    archive = r.content

    doc = json.loads(
        zipfile.ZipFile(io.BytesIO(archive)).read("lifelogr.json")
    )
    assert doc["format"] == "lifelogr-archive"
    assert doc["version"] == 2
    assert doc["notes"], "v2 archive carries notes"
    assert doc["entries"][0]["events"], "v2 archive carries entry events"

    await _wipe(db_session, media_dir)

    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("lifelogr-archive.zip", archive, "application/zip")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1

    # ── Entries, media, events came back ──
    from app.models.entry import Entry
    from app.models.entry_event import EntryEvent
    from app.models.media import Media
    from app.models.note import Note
    from app.models.note_media import NoteMedia

    entry = (await db_session.execute(select(Entry))).scalar_one()
    assert entry.title == "V2 entry"
    event = (await db_session.execute(select(EntryEvent))).scalar_one()
    assert (event.kind, event.content, event.label) == ("weather", "72 / 55 °F", "Clear")
    media = (await db_session.execute(select(Media))).scalar_one()
    assert media.filename == "photo.jpg"
    assert (media_dir / media.storage_path).read_bytes() == b"\xff\xd8\xff\xe0jpeg-bytes"

    # ── Notes + attachments came back, body URL remapped to the new ids ──
    note = (await db_session.execute(select(Note))).scalar_one()
    assert note.title == "V2 note"
    note_media = (await db_session.execute(select(NoteMedia))).scalar_one()
    assert note_media.filename == "receipt.pdf"
    assert (media_dir / note_media.storage_path).read_bytes() == b"%PDF-1.7 pdf-bytes"
    assert (
        f"/api/v1/notes/{note.id}/media/{note_media.id}/file" in note.body
    ), "note body URL rewritten to the imported ids"
    assert "/media/55/file" not in note.body


async def test_v1_archive_still_imports(db_session, client, media_dir):
    doc = {
        "format": "lifelogr-archive",
        "version": 1,
        "entries": [
            {
                "entry_date": "2026-06-02",
                "title": "V1 entry",
                "body": "Legacy",
                "mood": None,
                "tags": ["old"],
                "latitude": None,
                "longitude": None,
                "media": [],
            }
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("lifelogr.json", json.dumps(doc))
    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("v1.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1
    from app.models.entry import Entry

    entry = (await db_session.execute(select(Entry))).scalar_one()
    assert entry.title == "V1 entry"
