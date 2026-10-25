"""DM10 — .diary writer fidelity: trackers, container pragmas, round-trip.

The exported SQLite file must match what a real Diarium backup looks like
(docs/diarium-format-analysis.md §1/§3.6): Tags.Type=2 trackers with verbatim
EntryTags.TrackingValue, user_version 4, journal_mode delete — and a re-import
of the file reproduces the tracker readings.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pytest

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.tag import EntryTag
from app.services.export_service import build_diarium_database
from app.services.importers.diarium import parse_diarium_sqlite

pytestmark = pytest.mark.asyncio


async def _seed_entry_with_trackers(db_session) -> int:
    from app.models.entry import Entry
    from app.models.tag import EntryTag, Tag

    entry = Entry(
        entry_date=date(2026, 6, 12),
        title="Weigh-in",
        body="Weekly weigh-in.",
        mood="good",
        latitude=48.8584,
        longitude=2.2945,
    )
    db_session.add(entry)
    tracker = Tag(name="weight", is_tracker=True)
    plain = Tag(name="health")
    db_session.add_all([tracker, plain])
    await db_session.flush()
    db_session.add_all(
        [
            EntryTag(entry_id=entry.id, tag_id=tracker.id, tracking_value="84.5kg"),
            EntryTag(entry_id=entry.id, tag_id=plain.id),
        ]
    )
    await db_session.commit()
    return entry.id


async def _load(db_session, entry_id: int):
    from app.models.entry import Entry

    return (
        await db_session.execute(
            select(Entry)
            .options(
                selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
                selectinload(Entry.events),
            )
            .where(Entry.id == entry_id)
        )
    ).scalar_one()


def _open_diary(data: bytes) -> sqlite3.Connection:
    tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
    tmp.close()
    Path(tmp.name).write_bytes(data)
    return sqlite3.connect(tmp.name)


async def test_export_writes_trackers_and_container_pragmas(db_session):
    entry_id = await _seed_entry_with_trackers(db_session)
    loaded = await _load(db_session, entry_id)
    data = await build_diarium_database([loaded])

    # ── Container properties (§1) ──
    conn = _open_diary(data)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        tags = dict(conn.execute("SELECT Value, Type FROM Tags").fetchall())
        assert tags == {"weight": 2, "health": 0}
        tracking = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT t.Value, et.TrackingValue FROM EntryTags et "
                "JOIN Tags t ON t.DiaryTagId = et.DiaryTagId"
            ).fetchall()
        }
        assert tracking["weight"] == "84.5kg"  # verbatim reading
        assert tracking["health"] is None
        # AUTOINCREMENT state is sane after inserts.
        seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
        assert seq["Tags"] >= 2
        # Rating / Lat / Long written through.
        rating, lat, lon = conn.execute(
            "SELECT Rating, Latitude, Longitude FROM Entries"
        ).fetchone()
        assert (rating, lat, lon) == (4, 48.8584, 2.2945)
    finally:
        conn.close()

    # ── Round-trip: the readings survive a re-import ──
    parsed = parse_diarium_sqlite(data)
    assert len(parsed) == 1
    assert parsed[0]["trackers"] == [{"name": "weight", "value": "84.5kg"}]
    assert "health" in parsed[0]["tags"]


async def test_same_day_entries_get_distinct_ticks(db_session):
    """Two same-day entries must not collide on the DiaryEntryId PK."""
    from app.models.entry import Entry

    db_session.add_all(
        [
            Entry(entry_date=date(2026, 6, 12), body="First"),
            Entry(entry_date=date(2026, 6, 12), body="Second"),
        ]
    )
    await db_session.commit()
    loaded = (
        await db_session.execute(
            select(Entry).options(selectinload(Entry.events)).order_by(Entry.id)
        )
    ).scalars().all()
    data = await build_diarium_database(list(loaded))

    conn = _open_diary(data)
    try:
        ids = [r[0] for r in conn.execute("SELECT DiaryEntryId FROM Entries").fetchall()]
        assert len(ids) == 2 and len(set(ids)) == 2
        # Both ticks land on the same calendar day (offset by whole seconds).
        assert abs(ids[1] - ids[0]) < 86_400 * 10_000_000
    finally:
        conn.close()
