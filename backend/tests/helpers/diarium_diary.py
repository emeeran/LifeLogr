"""Synthetic Diarium ``.diary`` builder for tests.

Produces a tiny SQLite file with the real Diarium schema (verified against
the shipped 3.3.12.0 binary; see docs/diarium-format-analysis.md) so suites
never touch a real personal backup and can exercise unobserved enum values
(``Tags.Type=2``, ``Events.Type!=0``, ``Media.Type=2``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

# .NET DateTime.Ticks epoch — 0001-01-01 (DiaryEntryId base).
DOTNET_TICKS_EPOCH = 621355968000000000

_DIARY_DDL = """
CREATE TABLE Entries(DiaryEntryId bigint primary key not null, Heading varchar not null,
                     Text varchar not null, Rating integer not null,
                     Latitude float not null, Longitude float not null);
CREATE TABLE EntryTags(DiaryEntryId bigint not null, DiaryTagId integer not null,
                       TrackingValue varchar);
CREATE TABLE Events(DiaryEventId integer primary key autoincrement not null,
                    Type integer not null, Content varchar not null, Tag varchar,
                    DiaryEntryId bigint not null);
CREATE TABLE Media(DiaryMediaId varchar(36) primary key not null, Type integer not null,
                   Data blob, Name varchar not null, FileEnding varchar not null,
                   "Index" integer not null, DiaryEntryId bigint not null);
CREATE TABLE Tags(DiaryTagId integer primary key autoincrement not null,
                  Value varchar not null, Type integer not null, Color varchar, Icon varchar);
CREATE TABLE Templates(TemplateId integer primary key autoincrement not null,
                       Name varchar not null, Heading varchar not null,
                       Text varchar not null, Tags varchar not null);
"""


def ticks_for(date_str: str) -> int:
    """.NET ticks for a YYYY-MM-DD date at noon UTC (matches real backups'
    local-wall-clock encoding closely enough for day-level imports)."""
    dt = datetime.fromisoformat(date_str).replace(
        hour=12, tzinfo=timezone.utc
    )
    return DOTNET_TICKS_EPOCH + int(dt.timestamp()) * 10_000_000


def build_diary(
    entries: list[dict[str, Any]],
    *,
    include_media: bool = False,
    include_templates: bool = False,
) -> bytes:
    """Build a .diary file from a compact spec.

    Each entry dict: ``date`` (YYYY-MM-DD), optional ``heading``/``text``/
    ``rating`` (default 0)/``lat``/``lon``, ``tags`` (list of ``Value``),
    ``tag_types`` (optional parallel list of ``Tags.Type`` — e.g. 2 for a
    tracker), ``events`` (list of ``(type, content, tag)`` tuples),
    ``tracking`` (optional per-tag TrackingValue — paired with tags by index).
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(_DIARY_DDL)
    used_ticks: set[int] = set()
    try:
        for spec in entries:
            ticks = ticks_for(spec["date"])
            # Same-day entries need distinct PKs — nudge by whole seconds.
            while ticks in used_ticks:
                ticks += 10_000_000
            used_ticks.add(ticks)
            conn.execute(
                "INSERT INTO Entries (DiaryEntryId, Heading, Text, Rating, Latitude, "
                "Longitude) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticks,
                    spec.get("heading", ""),
                    spec.get("text", ""),
                    spec.get("rating", 0),
                    spec.get("lat", 0.0),
                    spec.get("lon", 0.0),
                ),
            )
            tags = spec.get("tags", [])
            tag_types = spec.get("tag_types", [0] * len(tags))
            tracking = spec.get("tracking", [])
            for i, value in enumerate(tags):
                cur = conn.execute(
                    "INSERT INTO Tags (Value, Type) VALUES (?, ?)",
                    (value, tag_types[i]),
                )
                conn.execute(
                    "INSERT INTO EntryTags (DiaryEntryId, DiaryTagId, TrackingValue) "
                    "VALUES (?, ?, ?)",
                    (ticks, cur.lastrowid, tracking[i] if i < len(tracking) else None),
                )
            for event_type, content, label in spec.get("events", []):
                conn.execute(
                    "INSERT INTO Events (Type, Content, Tag, DiaryEntryId) "
                    "VALUES (?, ?, ?, ?)",
                    (event_type, content, label, ticks),
                )
            if include_media and spec.get("media"):
                for idx, item in enumerate(spec["media"]):
                    # (name, ext, blob) or {"name", "ext", "blob", "type"} —
                    # the dict form exercises unobserved Types (e.g. 2).
                    if isinstance(item, dict):
                        name, ext, blob, media_type = (
                            item["name"],
                            item["ext"],
                            item["blob"],
                            item.get("type", 0),
                        )
                    else:
                        name, ext, blob = item
                        media_type = 0
                    conn.execute(
                        'INSERT INTO Media (DiaryMediaId, Type, Data, Name, FileEnding, '
                        '"Index", DiaryEntryId) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (f"guid-{ticks}-{idx}", media_type, blob, name, ext, idx, ticks),
                    )
        if include_templates:
            conn.execute(
                "INSERT INTO Templates (Name, Heading, Text, Tags) VALUES "
                "('Daily', 'Today', '<p>…</p>', '')"
            )
        # Real backups are user_version 4 (format analysis §1).
        conn.execute("PRAGMA user_version = 4")
        conn.commit()

        # Serialize to bytes via a temp file (same mechanism as the exporter —
        # conn.serialize() isn't available under the frozen pysqlite3 swap).
        import tempfile
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        try:
            with sqlite3.connect(tmp.name) as out:
                conn.backup(out)
            return Path(tmp.name).read_bytes()
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    finally:
        conn.close()


# ── Structural validator (docs/diarium-format-analysis.md §2/§3) ────────────

_DIARIUM_TABLES = {"Entries", "EntryTags", "Events", "Media", "Tags", "Templates"}

# First blob bytes a Media.Type must show (§3.4). Type 2 is unobserved in the
# wild — any blob accepted.
_MEDIA_MAGIC = {
    0: (b"\xff\xd8\xff",),  # JPEG
    1: (b"ID3", b"\x00\x00\x00"),  # mp3 / m4a(ftyp box starts with size)
    3: (b"%PDF-",),
    4: (b"\x00\x00\x00",),  # mp4 ftyp box size prefix
}


def validate_diary(data: bytes) -> None:
    """Assert *data* is structurally faithful to the Diarium .diary schema.

    Raises ``AssertionError`` describing the first violation. Covers the
    container (§1), the six-table schema (§2), tick sanity (§3.1), the
    Media Name/FileEnding/Index/blob-magic encodings (§3.4) and the
    autoincrement bookkeeping (§4).
    """
    import tempfile as _tempfile
    from datetime import datetime as _datetime

    tmp = _tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
    tmp.write(data)
    tmp.close()
    try:
        conn = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == 4, f"user_version is {version}, expected 4"

            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing = _DIARIUM_TABLES - names
            assert not missing, f"missing Diarium tables: {sorted(missing)}"

            now_ticks = int(
                (
                    _datetime.now().replace(microsecond=0) - _datetime(1, 1, 1)
                ).total_seconds()
                * 10_000_000
            )
            for row in conn.execute(
                "SELECT DiaryEntryId, Rating, Latitude, Longitude FROM Entries"
            ).fetchall():
                ticks = row["DiaryEntryId"]
                assert ticks > 0, f"negative ticks: {ticks}"
                # .NET ticks are 100ns since 0001-01-01; anything that decodes
                # outside 1970–2100 is not a sane entry timestamp.
                assert (
                    DOTNET_TICKS_EPOCH + 50 * 365.25 * 24 * 3600 * 10_000_000
                    < ticks
                    < now_ticks + 75 * 365.25 * 24 * 3600 * 10_000_000
                ), f"ticks out of the plausible range: {ticks}"
                assert 0 <= row["Rating"] <= 5, f"Rating out of range: {row['Rating']}"

            for row in conn.execute(
                'SELECT DiaryEntryId, Type, Data, FileEnding, "Index" FROM Media'
            ).fetchall():
                ending = row["FileEnding"] or ""
                assert ending == "" or ending.startswith(
                    "."
                ), f"FileEnding not dotted: {ending!r}"
                assert row["Index"] >= 0, f"negative media Index: {row['Index']}"
            # Index must be dense from 0 within each entry.
            for entry_id, in conn.execute(
                "SELECT DISTINCT DiaryEntryId FROM Media"
            ).fetchall():
                indexes = [
                    r[0]
                    for r in conn.execute(
                        'SELECT "Index" FROM Media WHERE DiaryEntryId = ? ORDER BY "Index"',
                        (entry_id,),
                    ).fetchall()
                ]
                assert indexes == list(range(len(indexes))), (
                    f"Index not dense from 0 for entry {entry_id}: {indexes}"
                )

            for row in conn.execute(
                "SELECT Type, Data FROM Media WHERE Data IS NOT NULL"
            ).fetchall():
                blob = row["Data"]
                magics = _MEDIA_MAGIC.get(row["Type"])
                if magics:
                    assert any(blob.startswith(m) for m in magics), (
                        f"blob magic {blob[:8]!r} does not match Type={row['Type']}"
                    )

            for table, pk in (("Tags", "DiaryTagId"), ("Events", "DiaryEventId")):
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM sqlite_sequence WHERE name = ?",
                    (table,),
                ).fetchone()
                max_id = conn.execute(f"SELECT COALESCE(MAX({pk}), 0) FROM {table}").fetchone()[0]
                if row is not None:
                    assert row[0] >= max_id, (
                        f"sqlite_sequence behind {table}: {row[0]} < {max_id}"
                    )
        finally:
            conn.close()
    finally:
        import os as _os

        _os.unlink(tmp.name)
