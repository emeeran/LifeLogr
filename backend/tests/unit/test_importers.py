"""Tests for entry import parsers (CSV, Day One) + JSON round-trip + dedup."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import date, datetime, timezone

import pytest

from app.services.importers import (
    parse_csv,
    parse_diarium_json_entry,
    parse_diarium_sqlite,
    parse_dayone_zip,
    parse_markdown_entry,
)


# ── CSV parser ───────────────────────────────────────────────────────────────


def test_parse_csv_basic():
    text = "date,title,body,mood,tags\n2024-01-01,Hello,Body one,good,a;b\n2024-01-02,,Body two,,\n"
    rows = parse_csv(text)
    assert len(rows) == 2
    assert rows[0] == {
        "entry_date": "2024-01-01",
        "title": "Hello",
        "body": "Body one",
        "mood": "good",
        "tags": ["a", "b"],
    }
    assert rows[1]["title"] is None
    assert rows[1]["tags"] == []


def test_parse_csv_rating_maps_to_mood():
    text = "entry_date,body,rating\n2024-01-03,text,5\n2024-01-04,text2,1\n"
    rows = parse_csv(text)
    assert rows[0]["mood"] == "great"
    assert rows[1]["mood"] == "awful"


def test_parse_csv_alternate_headers_skips_empty():
    # body under "content"; a row missing body is skipped
    text = "Entry Date,content\n2024-01-05,kept\n2024-01-06,\n"
    rows = parse_csv(text)
    assert len(rows) == 1
    assert rows[0]["body"] == "kept"
    assert rows[0]["entry_date"] == "2024-01-05"


def test_parse_csv_tag_split_pipe():
    # The tags field is quoted so its internal ", " isn't treated as a delimiter.
    text = 'date,body,tags\n2024-01-07,b,"t1 | t2 , t3"\n'
    rows = parse_csv(text)
    assert rows[0]["tags"] == ["t1", "t2", "t3"]


# ── Day One parser ───────────────────────────────────────────────────────────


def _dayone_zip(entries: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Journal.json", json.dumps({"entries": entries}))
    return buf.getvalue()


def test_parse_dayone_zip():
    entries = [
        {
            "creationDate": "2024-02-01T08:00:00Z",
            "text": "Day one entry",
            "title": "Title",
            "tags": ["travel"],
            "location": {"latitude": 12.3, "longitude": 45.6},
        },
        {"creationDate": "2024-02-02T08:00:00Z", "text": "No tags"},
        {"creationDate": "2024-02-03T08:00:00Z"},  # no body → skipped
    ]
    rows = parse_dayone_zip(_dayone_zip(entries))
    assert len(rows) == 2
    assert rows[0]["entry_date"] == "2024-02-01"
    assert rows[0]["body"] == "Day one entry"
    assert rows[0]["tags"] == ["travel"]
    assert rows[0]["latitude"] == 12.3
    assert rows[1]["tags"] == []


def test_parse_dayone_not_a_dayone_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("entries.json", json.dumps([{"date": "x"}]))
    assert parse_dayone_zip(buf.getvalue()) == []


# ── JSON export round-trip + duplicate skipping (via HTTP) ───────────────────


@pytest.mark.asyncio
async def test_export_import_json_roundtrip_and_dedup(client, db_session):
    from app.models.entry import Entry

    db_session.add(
        Entry(entry_date=date(2024, 3, 3), title="T", body="roundtrip body", mood="good")
    )
    await db_session.commit()

    r = await client.get("/api/v1/entries/export/json")
    assert r.status_code == 200
    payload = r.json()
    assert payload["app"] == "lifelogr"
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["body"] == "roundtrip body"

    export_bytes = json.dumps(payload).encode()

    # Re-importing with dedup on (default) skips the already-present entry.
    r2 = await client.post(
        "/api/v1/entries/import/file",
        params={"skip_duplicates": "true"},
        files={"file": ("exp.json", export_bytes, "application/json")},
    )
    assert r2.status_code == 200
    assert r2.json()["imported"] == 0
    assert r2.json()["skipped"] == 1

    # With dedup off, the entry is imported again.
    r3 = await client.post(
        "/api/v1/entries/import/file",
        params={"skip_duplicates": "false"},
        files={"file": ("exp.json", export_bytes, "application/json")},
    )
    assert r3.status_code == 200
    assert r3.json()["imported"] == 1


@pytest.mark.asyncio
async def test_import_csv_via_endpoint(client):
    csv_text = "date,title,body,mood,tags\n2024-05-05,Csv,Body csv,good,a;b\n2024-05-06,,More,,\n"
    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("entries.csv", csv_text.encode(), "text/csv")},
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 2


# ── Diarium JSON + markdown parsers (extracted from the entries router) ──────


def test_parse_diarium_json_entry_strips_html_and_maps_mood():
    parsed = parse_diarium_json_entry(
        {"date": "2026-03-04T00:00:00", "heading": "<b>Title</b>", "html": "<p>Body</p>", "rating": 5}
    )
    assert parsed["entry_date"] == "2026-03-04"
    assert parsed["title"] == "Title"  # HTML stripped from heading
    assert parsed["body"] == "Body"  # HTML stripped to text
    assert parsed["mood"] == "great"  # rating 5 -> great
    assert parsed["tags"] == []


def test_parse_markdown_entry_reads_frontmatter():
    raw = "---\ndate: 2026-02-01\nmood: good\ntags:\n  - work\n  - trip\n---\n\nThe body."
    parsed = parse_markdown_entry(raw)
    assert parsed is not None
    assert parsed["entry_date"] == "2026-02-01"
    assert parsed["mood"] == "good"
    assert parsed["tags"] == ["work", "trip"]
    assert parsed["body"] == "The body."


def test_parse_diarium_sqlite_converts_ticks_and_maps_rating(tmp_path):
    db = tmp_path / "test.diary"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE Entries (DiaryEntryId INTEGER, Heading TEXT, Text TEXT, "
        "Rating REAL, Latitude REAL, Longitude REAL)"
    )
    conn.execute("CREATE TABLE EntryTags (DiaryEntryId INTEGER, DiaryTagId INTEGER)")
    conn.execute("CREATE TABLE Tags (DiaryTagId INTEGER, Value TEXT)")
    # DiaryEntryId is .NET ticks (100ns since 0001-01-01); 621355968000000000 is
    # the Unix-epoch offset the parser subtracts.
    target = datetime(2026, 1, 15, tzinfo=timezone.utc)
    ticks = 621355968000000000 + int(target.timestamp()) * 10_000_000
    conn.execute(
        "INSERT INTO Entries VALUES (?, ?, ?, ?, NULL, NULL)",
        (ticks, "<b>My Title</b>", "Hello world", 4),
    )
    conn.execute("INSERT INTO EntryTags VALUES (?, 1)", (ticks,))
    conn.execute("INSERT INTO Tags VALUES (1, 'work')")
    conn.commit()
    conn.close()

    entries = parse_diarium_sqlite(db.read_bytes())
    assert len(entries) == 1
    e = entries[0]
    assert e["entry_date"] == "2026-01-15"  # ticks -> date
    assert e["title"] == "My Title"  # HTML stripped
    assert e["body"] == "Hello world"
    assert e["mood"] == "good"  # rating 4 -> good
    assert e["tags"] == ["work"]  # joined via EntryTags/Tags
    assert e["latitude"] is None and e["longitude"] is None


# ── Diarium .diary SQLite EXPORT (round-trips with the importer above) ───────


@pytest.mark.asyncio
async def test_export_diarium_db_builds_diarium_schema(client, db_session, tmp_path):
    import sqlite3

    from app.models.entry import Entry

    db_session.add(
        Entry(entry_date=date(2026, 1, 15), title="Hi", body="Line one\nLine two", mood="good")
    )
    await db_session.commit()

    r = await client.get("/api/v1/entries/export/diarium-db")
    assert r.status_code == 200

    # Parse the returned SQLite and confirm the Diarium schema + tick conversion.
    db_file = tmp_path / "export.diary"
    db_file.write_bytes(r.content)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT DiaryEntryId, Heading, Rating FROM Entries").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["Heading"] == "Hi"
    assert row["Rating"] == 4  # mood "good" -> 4 (inverse of the importer map)
    # DiaryEntryId is .NET ticks; the importer's offset converts it back to the date.
    ticks = row["DiaryEntryId"]
    us = (ticks - 621355968000000000) / 10
    assert datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%d") == "2026-01-15"
    conn.close()


# ── Diarium compatibility (schema extracted from the shipped 3.3.12.0 binary) ─
#
# The DDL below is copied verbatim from the CREATE TABLE strings inside
# Diarium.exe (SHA-256 5b8cc6fb…). Any drift between our .diary export and
# these statements — column names, NOT NULLs, the six-table set — means
# Diarium's backup restore will reject or mangle the file.

_DIARIUM_DDL_VERBATIM = [
    "CREATE TABLE Entries(DiaryEntryId bigint primary key not null, Heading varchar not null, Text varchar not null, Rating integer not null, Latitude float not null, Longitude float not null)",
    "CREATE TABLE EntryTags(DiaryEntryId bigint not null, DiaryTagId integer not null, TrackingValue varchar)",
    "CREATE TABLE Events(DiaryEventId integer primary key autoincrement not null, Type integer not null, Content varchar not null, Tag varchar, DiaryEntryId bigint not null )",
    'CREATE TABLE Media(DiaryMediaId varchar(36) primary key not null, Type integer not null, Data blob, Name varchar not null, FileEnding varchar not null, "Index" integer not null, DiaryEntryId bigint not null)',
    "CREATE TABLE Tags(DiaryTagId integer primary key autoincrement not null, Value varchar not null, Type integer not null, Color varchar, Icon varchar)",
    "CREATE TABLE Templates(TemplateId integer primary key autoincrement not null, Name varchar not null, Heading varchar not null, Text varchar not null, Tags varchar not null)",
]


def _real_diarium_db(tmp_path) -> "sqlite3.Connection":
    """A database with the real Diarium schema, for importer tests."""
    conn = sqlite3.connect(tmp_path / "real.diary")
    for ddl in _DIARIUM_DDL_VERBATIM:
        conn.execute(ddl)
    return conn


@pytest.mark.asyncio
async def test_export_diarium_db_matches_real_diarium_schema(client, tmp_path):
    """The .diary export must be byte-schema identical to a real Diarium backup."""
    r = await client.get("/api/v1/entries/export/diarium-db")
    assert r.status_code == 200
    db_file = tmp_path / "export.diary"
    db_file.write_bytes(r.content)
    conn = sqlite3.connect(db_file)
    got = sorted(
        (row[0] or "").replace("  ", " ")
        for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")
        # sqlite_sequence comes with AUTOINCREMENT — real Diarium backups
        # carry it too; it's runtime bookkeeping, not part of the contract.
        if row[0] and not row[0].startswith("CREATE TABLE sqlite_sequence")
    )
    conn.close()
    assert got == sorted(_DIARIUM_DDL_VERBATIM)


@pytest.mark.asyncio
async def test_export_diarium_db_satisfies_not_null_and_round_trips(client, db_session, tmp_path):
    """Exported rows must satisfy the real schema's NOT NULLs and re-import losslessly."""
    from app.models.entry import Entry
    from app.models.tag import Tag

    e = Entry(
        entry_date=date(2026, 2, 3),
        title="Trip day",
        body="Went hiking.\n\nSaw a lake.",
        mood="great",
        # None lat/lon — real columns are NOT NULL, export must coalesce.
    )
    db_session.add(e)
    await db_session.flush()
    db_session.add(Tag(name="hiking"))
    await db_session.flush()
    from app.models.tag import EntryTag

    db_session.add(EntryTag(entry_id=e.id, tag_id=1))
    await db_session.commit()

    r = await client.get("/api/v1/entries/export/diarium-db")
    db_file = tmp_path / "rt.diary"
    db_file.write_bytes(r.content)

    # 1. The real schema's NOT NULL constraints accept every exported row.
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA ignore_check_constraints = OFF")
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    count = conn.execute(
        "SELECT COUNT(*) FROM Entries WHERE Latitude IS NULL OR Longitude IS NULL "
        "OR Heading IS NULL OR Text IS NULL"
    ).fetchone()[0]
    assert count == 0
    tag_type = conn.execute("SELECT Type FROM Tags WHERE Value='hiking'").fetchone()
    assert tag_type is not None and tag_type[0] == 0  # 0 = plain tag
    conn.close()

    # 2. Round trip: our own importer reads it back.
    entries = parse_diarium_sqlite(db_file.read_bytes())
    assert len(entries) == 1
    got = entries[0]
    assert got["entry_date"] == "2026-02-03"
    assert got["title"] == "Trip day"
    assert "Went hiking." in got["body"]
    assert got["mood"] == "great"
    assert got["tags"] == ["hiking"]


def test_parse_diarium_sqlite_imports_tags_and_persons_skips_trackers(tmp_path):
    """Tags.Type: 0 = tag and 1 = person import; 2 = tracker is skipped."""
    conn = _real_diarium_db(tmp_path)
    target = datetime(2026, 1, 15, tzinfo=timezone.utc)
    ticks = 621355968000000000 + int(target.timestamp()) * 10_000_000
    conn.execute(
        "INSERT INTO Entries VALUES (?, 'Title', '<p>Body</p>', 3, 0.0, 0.0)", (ticks,)
    )
    for tag_id, value, tag_type in [(1, "work", 0), (2, "Alice", 1), (3, "Gym", 2)]:
        conn.execute(
            "INSERT INTO Tags (DiaryTagId, Value, Type) VALUES (?, ?, ?)",
            (tag_id, value, tag_type),
        )
        conn.execute(
            "INSERT INTO EntryTags (DiaryEntryId, DiaryTagId) VALUES (?, ?)", (ticks, tag_id)
        )
    conn.commit()
    conn.close()

    entries = parse_diarium_sqlite((tmp_path / "real.diary").read_bytes())
    assert len(entries) == 1
    # "Gym" is a tracker (boolean check-off) — excluded; tag and person kept.
    assert sorted(entries[0]["tags"]) == ["Alice", "work"]
    # <p>Body</p> HTML is stripped to plain text.
    assert entries[0]["body"] == "Body"


def test_parse_diarium_json_entry_accepts_real_diarium_shape():
    """Diarium's own JSON object model: tick-keyed, capitalized field names."""
    # 2026-01-15 00:00:00 local as .NET ticks.
    ticks = 621355968000000000 + int(datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp()) * 10_000_000
    parsed = parse_diarium_json_entry(
        {
            "DiaryEntryId": ticks,
            "Heading": "Real Diarium",
            "Text": "<p>Hello <b>world</b></p><p>Second para</p>",
            "Rating": 5,
            "Tags": ["holiday", "Alice"],
        }
    )
    assert parsed["entry_date"] == "2026-01-15"
    assert parsed["title"] == "Real Diarium"
    assert parsed["body"] == "Hello world\n\nSecond para"  # HTML stripped, paragraphs split
    assert parsed["mood"] == "great"
    assert parsed["tags"] == ["holiday", "Alice"]


@pytest.mark.asyncio
async def test_daylio_csv_export_round_trips_through_csv_import(client, db_session):
    """The Daylio CSV we emit is exactly what Diarium's CSV importer reads —
    so it must also re-import here (header spelling, rad->great, pipe tags)."""
    from app.models.entry import Entry
    from app.models.tag import EntryTag, Tag

    e = Entry(entry_date=date(2026, 3, 9), title="Office", body="Long day.", mood="great")
    db_session.add(e)
    await db_session.flush()
    t = Tag(name="work")
    db_session.add(t)
    await db_session.flush()
    db_session.add(EntryTag(entry_id=e.id, tag_id=t.id))
    await db_session.commit()

    r = await client.get("/api/v1/entries/export/daylio-csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8")
    first_line = text.splitlines()[0]
    assert first_line == "full_date,date,weekday,time,mood,activities,note_title,note"
    assert "rad" in text  # great -> Daylio's "rad"
    assert "Monday" in text  # 2026-03-09 is a Monday

    # Round trip through the CSV importer (the same shape Diarium reads).
    imported = parse_csv(text)
    assert len(imported) == 1
    row = imported[0]
    assert row["entry_date"] == "2026-03-09"
    assert row["title"] == "Office"
    assert row["body"] == "Long day."
    assert row["mood"] == "great"  # rad -> great
    assert row["tags"] == ["work"]


# ── Media round-trips (archive ZIP, .diary blobs, Markdown ZIP) ──────────────


async def _seed_entry_with_media(db_session, monkeypatch, tmp_path):
    """An entry with a photo on disk and its URL embedded in the body."""
    from app.core.config import settings
    from app.models.entry import Entry
    from app.models.media import Media

    media_root = tmp_path / "media"
    (media_root / "images").mkdir(parents=True)
    monkeypatch.setattr(settings, "MEDIA_DIR", media_root)

    entry = Entry(
        entry_date=date(2026, 5, 1),
        title="Photo day",
        body="Here is a photo:\n\n![pic](/api/v1/media/PLACEHOLDER/file)",
        mood="good",
    )
    db_session.add(entry)
    await db_session.flush()
    blob = b"\xff\xd8\xff\xe0FAKEJPEGDATA"
    media = Media(
        entry_id=entry.id,
        filename="photo.jpg",
        media_type="image",
        file_size=len(blob),
        storage_path="images/rt-test.jpg",
        caption="A lake",
        is_inline=True,
    )
    db_session.add(media)
    await db_session.flush()
    (media_root / "images" / "rt-test.jpg").write_bytes(blob)
    entry.body = entry.body.replace("PLACEHOLDER", str(media.id))
    await db_session.commit()
    return entry, media, blob


@pytest.mark.asyncio
async def test_archive_export_import_round_trips_media(client, db_session, tmp_path, monkeypatch):
    """Native archive: media bytes + metadata survive, body URLs are remapped."""
    from app.models.media import Media

    entry, media, blob = await _seed_entry_with_media(db_session, monkeypatch, tmp_path)

    r = await client.get("/api/v1/entries/export/archive")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "lifelogr.json" in zf.namelist()
    doc = json.loads(zf.read("lifelogr.json"))
    assert doc["format"] == "lifelogr-archive"
    assert doc["entries"][0]["media"][0]["ref"] == media.id
    assert zf.read(doc["entries"][0]["media"][0]["path"]) == blob

    # Re-import the same archive (skip_duplicates: the source entry is still there).
    imp = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("archive.zip", r.content, "application/zip")},
        params={"skip_duplicates": False},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["imported"] == 1

    new_media = (
        await db_session.execute(Media.__table__.select().where(Media.entry_id != entry.id))
    ).first()
    assert new_media is not None
    assert new_media.filename == "photo.jpg"
    assert (tmp_path / "media" / new_media.storage_path).read_bytes() == blob

    # The imported body references the NEW media id, not the old one.
    from sqlalchemy import text as sa_text

    reimported = (
        await db_session.execute(
            sa_text("SELECT body FROM entries WHERE id != :eid"), {"eid": entry.id}
        )
    ).scalar()
    assert f"/api/v1/media/{new_media.id}/file" in reimported
    assert f"/api/v1/media/{media.id}/file" not in reimported
    assert "![pic]" in reimported  # the markdown itself is preserved


@pytest.mark.asyncio
async def test_diarium_db_export_includes_media_blobs_and_reimports(
    client, db_session, tmp_path, monkeypatch
):
    """Media rows are embedded as real Diarium Media blobs — and re-import here."""
    entry, media, blob = await _seed_entry_with_media(db_session, monkeypatch, tmp_path)

    r = await client.get("/api/v1/entries/export/diarium-db")
    assert r.status_code == 200
    diary_file = tmp_path / "with-media.diary"
    diary_file.write_bytes(r.content)
    conn = sqlite3.connect(diary_file)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT Type, Data, Name, FileEnding FROM Media").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["Type"] == 0  # image
    assert rows[0]["Data"] == blob
    assert rows[0]["Name"] == "photo" and rows[0]["FileEnding"] == ".jpg"

    # Our .diary importer extracts the blob back into an import payload.
    parsed = parse_diarium_sqlite(diary_file.read_bytes())
    assert len(parsed) == 1
    assert parsed[0]["media"][0]["filename"] == "photo.jpg"
    assert parsed[0]["media"][0]["media_type"] == "image"
    assert parsed[0]["media"][0]["data"] == blob


@pytest.mark.asyncio
async def test_markdown_zip_export_import_round_trips_media(
    client, db_session, tmp_path, monkeypatch
):
    """Markdown ZIP: frontmatter media manifest re-attaches files on import."""
    from sqlalchemy import text as sa_text


    entry, media, blob = await _seed_entry_with_media(db_session, monkeypatch, tmp_path)

    r = await client.get("/api/v1/entries/export/markdown")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    md_name = next(n for n in zf.namelist() if n.endswith(".md"))
    raw = zf.read(md_name).decode()
    assert "media:" in raw
    assert f"path: media/{media.storage_path}" in raw
    assert zf.read(f"media/{media.storage_path}") == blob

    imp = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("export.zip", r.content, "application/zip")},
        params={"skip_duplicates": False},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["imported"] == 1

    reimported_body = (
        await db_session.execute(
            sa_text("SELECT body FROM entries WHERE id != :eid"), {"eid": entry.id}
        )
    ).scalar()
    new_media = (
        await db_session.execute(
            sa_text("SELECT id, storage_path FROM media WHERE entry_id != :eid"),
            {"eid": entry.id},
        )
    ).first()
    assert new_media is not None
    assert f"/api/v1/media/{new_media.id}/file" in reimported_body
    assert (tmp_path / "media" / new_media.storage_path).read_bytes() == blob


def test_parse_markdown_media_manifest_does_not_pollute_tags():
    raw = (
        "---\ndate: 2026-05-01\ntags:\n  - work\nmedia:\n"
        "  - ref: 42\n    path: media/images/x.jpg\n    filename: x.jpg\n    type: image\n"
        "---\n\nBody."
    )
    parsed = parse_markdown_entry(raw)
    assert parsed["tags"] == ["work"]  # the media items must not become tags
    assert parsed["media"] == [
        {"ref": "42", "path": "media/images/x.jpg", "filename": "x.jpg", "type": "image"}
    ]
