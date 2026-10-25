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
    try:
        for spec in entries:
            ticks = ticks_for(spec["date"])
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
                for idx, (name, ext, blob) in enumerate(spec["media"]):
                    conn.execute(
                        'INSERT INTO Media (DiaryMediaId, Type, Data, Name, FileEnding, '
                        '"Index", DiaryEntryId) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (f"guid-{ticks}-{idx}", 0, blob, name, ext, idx, ticks),
                    )
        if include_templates:
            conn.execute(
                "INSERT INTO Templates (Name, Heading, Text, Tags) VALUES "
                "('Daily', 'Today', '<p>…</p>', '')"
            )
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
