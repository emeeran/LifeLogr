"""DM8 — local backup/restore completeness round-trip.

Seeds every content kind the app stores (entries, tags, tracker readings,
entry events, entry media, notes, note pages, note attachments), packs the
real local ``.tar.gz`` backup via ``GET /backup/export``, wipes DATA_DIR,
restores through ``POST /backup/import``, and asserts every row and media
file comes back byte-identical with FTS serving the restored text.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.core.config import settings
from app.main import app



@pytest.fixture
async def http():
    """HTTP client without the conftest get_db/db_session override — the
    backup endpoints touch the filesystem paths, not a request session, and
    the override would repoint ``async_session`` away from the tmp DB."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def roundtrip_env(tmp_path: Path, monkeypatch):
    """Point the app's real data paths at a throwaway dir and init the DB."""
    data_dir = tmp_path / "data"
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'lifelogr.db'}"
    )

    from app.core.database import init_db, reinit_engine

    await reinit_engine()
    await init_db()
    yield data_dir, media_dir
    # Rebuild the global engine against the reverted settings so later tests
    # never touch the deleted tmp DB.
    await reinit_engine()


async def _seed(media_dir: Path) -> dict[str, bytes]:
    """Insert one of every content kind; return the media files it wrote."""
    from app.core.database import async_session
    from app.models.entry import Entry
    from app.models.entry_event import EntryEvent
    from app.models.media import Media
    from app.models.note import Note, NoteFolder, NotePage
    from app.models.note_media import NoteMedia
    from app.models.tag import EntryTag, Tag

    photo = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    receipt = b"%PDF-1.7 fake-pdf-bytes"

    async with async_session() as db:
        entry = Entry(
            entry_date=date(2026, 5, 1),
            title="Roundtrip entry",
            body="Morning walk with unmistakable-fts-token.",
            mood="good",
            latitude=48.8584,
            longitude=2.2945,
        )
        db.add(entry)
        await db.flush()

        tracker = Tag(name="weight", is_tracker=True)
        plain = Tag(name="garden")
        db.add_all([tracker, plain])
        await db.flush()
        db.add_all(
            [
                EntryTag(entry_id=entry.id, tag_id=tracker.id, tracking_value="84.5kg"),
                EntryTag(entry_id=entry.id, tag_id=plain.id),
                EntryEvent(
                    entry_id=entry.id, kind="weather", content="70 / 50 °F", label="Sunny"
                ),
                Media(
                    entry_id=entry.id,
                    filename="photo.jpg",
                    media_type="image",
                    file_size=len(photo),
                    storage_path="2026/05/photo.jpg",
                ),
            ]
        )

        folder = NoteFolder(name="KB")
        db.add(folder)
        await db.flush()
        note = Note(title="Roundtrip note", body="Note body with token.", folder_id=folder.id)
        db.add(note)
        await db.flush()
        db.add_all(
            [
                NotePage(note_id=note.id, title="Extra", body="Page body"),
                NoteMedia(
                    note_id=note.id,
                    filename="receipt.pdf",
                    media_type="document",
                    file_size=len(receipt),
                    storage_path="notes/receipt.pdf",
                ),
            ]
        )
        await db.commit()

    (media_dir / "2026" / "05").mkdir(parents=True, exist_ok=True)
    (media_dir / "2026" / "05" / "photo.jpg").write_bytes(photo)
    (media_dir / "notes").mkdir(parents=True, exist_ok=True)
    (media_dir / "notes" / "receipt.pdf").write_bytes(receipt)
    return {"2026/05/photo.jpg": photo, "notes/receipt.pdf": receipt}


async def test_backup_restore_roundtrip_is_complete(
    roundtrip_env, http, tmp_path: Path
) -> None:
    data_dir, media_dir = roundtrip_env
    seed_files = await _seed(media_dir)

    # ── Export ──
    r = await http.get("/api/v1/backup/export")
    assert r.status_code == 200
    archive = r.content

    # The tarball itself carries every media file.
    import io
    import tarfile

    tf = tarfile.open(fileobj=io.BytesIO(archive))
    tar_media = {
        m.name[len("media/"):] for m in tf.getmembers() if m.isfile() and m.name.startswith("media/")
    }
    assert tar_media == set(seed_files)

    # ── Wipe DATA_DIR (simulate a lost instance) ──
    for child in data_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    media_dir.mkdir(parents=True, exist_ok=True)

    # ── Restore ──
    r = await http.post(
        "/api/v1/backup/import",
        files={"file": ("backup.tar.gz", archive, "application/gzip")},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["restored"]) == {"database", "media"}

    # ── Rows came back ──
    from app.core.database import async_session
    from app.models.entry import Entry
    from app.models.entry_event import EntryEvent
    from app.models.media import Media
    from app.models.note import Note, NoteFolder, NotePage
    from app.models.note_media import NoteMedia
    from app.models.tag import EntryTag, Tag

    async with async_session() as db:
        entry = (await db.execute(select(Entry))).scalar_one()
        assert entry.title == "Roundtrip entry"
        assert entry.body == "Morning walk with unmistakable-fts-token."
        assert entry.mood == "good"
        assert (entry.latitude, entry.longitude) == (48.8584, 2.2945)

        pairs = (
            await db.execute(
                select(Tag, EntryTag).join(EntryTag, EntryTag.tag_id == Tag.id)
            )
        ).all()
        tracker_tag, assoc = next((t, a) for t, a in pairs if t.is_tracker)
        assert tracker_tag.name == "weight"
        assert assoc.tracking_value == "84.5kg"
        assert {t.name for t, _ in pairs} == {"weight", "garden"}
        assert (await db.execute(select(func.count()).select_from(Tag))).scalar() == 2

        event = (await db.execute(select(EntryEvent))).scalar_one()
        assert (event.kind, event.content, event.label) == (
            "weather",
            "70 / 50 °F",
            "Sunny",
        )

        media = (await db.execute(select(Media))).scalar_one()
        assert (media.filename, media.media_type, media.storage_path) == (
            "photo.jpg",
            "image",
            "2026/05/photo.jpg",
        )

        note = (await db.execute(select(Note))).scalar_one()
        assert note.title == "Roundtrip note"
        assert note.body == "Note body with token."
        assert (
            await db.execute(select(func.count()).select_from(NoteFolder))
        ).scalar() == 1
        page = (await db.execute(select(NotePage))).scalar_one()
        assert (page.title, page.body) == ("Extra", "Page body")
        note_media = (await db.execute(select(NoteMedia))).scalar_one()
        assert note_media.storage_path == "notes/receipt.pdf"

    # ── Media files byte-identical ──
    for rel, content in seed_files.items():
        assert (media_dir / rel).read_bytes() == content

    # ── FTS serves the restored text ──
    async with async_session() as db:
        hits = (
            await db.execute(
                text("SELECT count(*) FROM entries_fts WHERE entries_fts MATCH :q"),
                {"q": "unmistakable"},
            )
        ).scalar()
        assert hits == 1
        note_hits = (
            await db.execute(
                text("SELECT count(*) FROM notes_fts WHERE notes_fts MATCH :q"),
                {"q": "token"},
            )
        ).scalar()
        assert note_hits == 1
