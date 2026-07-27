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
