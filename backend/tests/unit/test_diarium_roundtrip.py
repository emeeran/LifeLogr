"""DM11 — .diary round-trip + structural validation.

Synthetic .diary (helpers/diarium_diary.py, exercising trackers, person
tags, unknown event types and Type=2 media) → lifelogr import → .diary
export → structural validation → re-import. Content must be equivalent
modulo the markdown↔HTML conversion; the structural validator must reject
a deliberately corrupted export.
"""

from __future__ import annotations

import pytest

from app.routers.entries import _run_entry_import
from app.services.export_service import build_diarium_database
from app.services.importers.diarium import parse_diarium_sqlite
from tests.helpers.diarium_diary import build_diary, validate_diary


_SPEC = [
    {
        "date": "2026-03-14",
        "heading": "Hike day",
        "text": "Long trail.\n\nSecond paragraph.",
        "rating": 4,
        "lat": 46.5,
        "lon": 8.0,
        "tags": ["outdoors", "hana", "weight"],
        "tag_types": [0, 1, 2],
        "tracking": [None, None, "63.2kg"],
        "events": [(0, "55 / 40 °F", "Sunny"), (9, "12,340", None)],
        "media": [
            {"name": "IMG_0001", "ext": ".jpg", "blob": b"\xff\xd8\xff\xe0jpeg"},
            # Type 2 is unobserved in the wild; lifelogr's importer maps it to
            # "document", so the blob is a real PDF (re-export writes Type 3).
            {"name": "scan", "ext": ".pdf", "blob": b"%PDF-1.7 scan", "type": 2},
        ],
    },
    {
        "date": "2026-03-14",
        "heading": "Evening",
        "text": "Second entry the same day.",
        "rating": 3,
    },
]


async def _import(db_session, data: bytes) -> list[dict]:
    parsed = parse_diarium_sqlite(data)
    result = await _run_entry_import(db_session, parsed, skip_duplicates=False)
    assert result["skipped"] == 0, result["skip_reasons"]
    return parsed


def _content_fingerprint(parsed: list[dict]) -> list[dict]:
    """Content comparable across import generations (modulo HTML/markdown)."""
    return [
        {
            "date": e["entry_date"],
            "title": e["title"],
            "body": " ".join((e["body"] or "").split()),
            "mood": e["mood"],
            "tags": sorted(e["tags"]),
            "trackers": sorted((t["name"], t["value"]) for t in e["trackers"]),
            "events": sorted((ev["kind"], ev["content"], ev["label"]) for ev in e["events"]),
            "media": sorted(
                (m["filename"], m["media_type"]) for m in e.get("media", [])
            ),
        }
        for e in sorted(parsed, key=lambda e: (e["entry_date"], e["body"] or ""))
    ]


async def test_diary_roundtrip_and_validation(db_session):
    original = await _import(db_session, build_diary(_SPEC, include_media=True))

    # Export the imported content back to .diary and structurally validate it.
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.entry import Entry
    from app.models.tag import EntryTag

    loaded = (
        await db_session.execute(
            select(Entry)
            .options(
                selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
                selectinload(Entry.events),
                selectinload(Entry.media),
            )
            .order_by(Entry.entry_date, Entry.id)
        )
    ).scalars().all()
    exported = await build_diarium_database(list(loaded))
    validate_diary(exported)  # must not raise

    # Re-import the export — content equivalent to the first generation.
    second = await _import(db_session, exported)
    assert len(second) == len(original)
    assert _content_fingerprint(original) == _content_fingerprint(second)


def test_validator_rejects_corrupted_export():
    good = build_diary(_SPEC, include_media=True)

    # Baseline: a good file passes.
    validate_diary(good)

    # Corruption 1: FileEnding loses its dot.
    import sqlite3
    import tempfile
    from pathlib import Path

    def corrupt(mutate):
        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        Path(tmp.name).write_bytes(good)
        conn = sqlite3.connect(tmp.name)
        mutate(conn)
        conn.commit()
        out = Path(tmp.name).read_bytes()
        conn.close()
        Path(tmp.name).unlink()
        return out

    def undot(conn):
        conn.execute("UPDATE Media SET FileEnding = 'jpg'")

    with pytest.raises(AssertionError, match="FileEnding"):
        validate_diary(corrupt(undot))

    def wrong_magic(conn):
        conn.execute("UPDATE Media SET Data = ? WHERE Type = 0", (b"not-a-jpeg",))

    with pytest.raises(AssertionError, match="magic"):
        validate_diary(corrupt(wrong_magic))

    def stale_sequence(conn):
        conn.execute("UPDATE sqlite_sequence SET seq = 1 WHERE name = 'Tags'")

    with pytest.raises(AssertionError, match="sqlite_sequence"):
        validate_diary(corrupt(stale_sequence))


async def test_path_import_streams_media(db_session, tmp_path):
    """Path source: blobs load lazily (never materialised at parse time) and
    still land in the database through the shared import loop."""
    from sqlalchemy import func, select

    from app.models.media import Media

    path = tmp_path / "device.diary"
    path.write_bytes(build_diary(_SPEC, include_media=True))

    parsed = parse_diarium_sqlite(path)
    media = [m for e in parsed for m in e["media"]]
    assert media
    assert all(m["data"] is None and callable(m["load"]) for m in media)
    assert path.exists()  # the parser must not delete the caller's file

    result = await _run_entry_import(db_session, parsed, skip_duplicates=False)
    assert result["skipped"] == 0, result["skip_reasons"]
    total = (await db_session.execute(select(func.sum(Media.file_size)))).scalar()
    assert total  # the lazy loads fetched real bytes onto disk


async def test_duplicate_import_backfills_missing_media_and_events(db_session):
    """A duplicate entry still gets back the media/events an older-backup
    restore dropped — and a repeat import must not double-attach."""
    from sqlalchemy import delete, func, select

    from app.models.entry_event import EntryEvent
    from app.models.media import Media

    data = build_diary(_SPEC, include_media=True)
    await _import(db_session, data)  # first pass: entries + media + events

    # Simulate the restore-from-older-backup loss: rows gone, text remains.
    await db_session.execute(delete(EntryEvent))
    await db_session.execute(delete(Media))
    await db_session.commit()

    result = await _run_entry_import(db_session, parse_diarium_sqlite(data), True)
    assert result["imported"] == 0
    assert result["media_backfilled"] == 2  # the two blobs on the "Hike day" entry
    assert (await db_session.execute(select(func.count()).select_from(Media))).scalar() == 2
    assert (await db_session.execute(select(func.count()).select_from(EntryEvent))).scalar() == 2

    # Idempotent: everything already present → nothing attached again.
    again = await _run_entry_import(db_session, parse_diarium_sqlite(data), True)
    assert again["media_backfilled"] == 0
    assert (await db_session.execute(select(func.count()).select_from(Media))).scalar() == 2
