"""Diarium Events (weather) import/export round-trip.

Covers the ``entry_events`` table end to end: the synthetic-.diary parser
(weather Type=0 verified, unobserved Types carried as ``unknown:<n>``),
persistence through the import route, the API surface, the .diary export
round-trip, and the schema-upgrade path (an existing DB gains the table on
boot; the legacy-table cleanup leaves it alone).
"""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.export_service import build_diarium_database
from app.services.importers.diarium import parse_diarium_sqlite
from tests.helpers.diarium_diary import build_diary


def _fixture_diary() -> bytes:
    """One entry carrying every observed + an unobserved event type."""
    return build_diary(
        [
            {
                "date": "2026-06-12",
                "heading": "Rainy day",
                "text": "Storm rolled in.",
                "rating": 4,
                "tags": ["weather-walk"],
                "events": [
                    (0, "84 / 74 °F", "Partly Cloudy"),  # verified weather
                    (7, "12,340", None),  # unobserved vendor type
                ],
            },
            {
                # Weather-only entry (no text, no media) — stays skipped, as
                # documented: auto-attached weather must not create empty days.
                "date": "2026-06-13",
                "events": [(0, "70 / 60 °F", "Sunny")],
            },
        ]
    )


class TestParse:
    def test_weather_and_unknown_types_parse(self):
        entries = parse_diarium_sqlite(_fixture_diary())
        assert len(entries) == 1  # the weather-only day is skipped
        events = entries[0]["events"]
        assert events == [
            {"kind": "weather", "content": "84 / 74 °F", "label": "Partly Cloudy"},
            {"kind": "unknown:7", "content": "12,340", "label": None},
        ]

    def test_diary_without_events_table(self):
        # Very old / hand-made databases predate the Events table (Tags and
        # EntryTags exist — the importer's baseline schema).
        import sqlite3
        import tempfile
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.executescript(
            "CREATE TABLE Entries (DiaryEntryId bigint primary key, Heading varchar, "
            "Text varchar, Rating integer, Latitude float, Longitude float);"
            "CREATE TABLE Tags (DiaryTagId integer primary key, Value varchar, Type integer);"
            "CREATE TABLE EntryTags (DiaryEntryId bigint, DiaryTagId integer);"
        )
        conn.commit()
        conn.close()
        data = Path(tmp.name).read_bytes()
        Path(tmp.name).unlink()
        assert parse_diarium_sqlite(data) == []


class TestImport:
    async def test_import_persists_events_and_api_exposes_them(
        self, client: AsyncClient, db_engine: AsyncEngine
    ):
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("backup.diary", _fixture_diary(), "application/octet-stream")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1

        async with db_engine.connect() as conn:
            found = (
                await conn.execute(
                    text("SELECT kind, content, label FROM entry_events ORDER BY id")
                )
            ).all()
            entry_id = (
                await conn.execute(text("SELECT id FROM entries LIMIT 1"))
            ).scalar()
        assert found == [
            ("weather", "84 / 74 °F", "Partly Cloudy"),
            ("unknown:7", "12,340", None),
        ]

        detail = await client.get(f"/api/v1/entries/{entry_id}")
        assert detail.status_code == 200
        assert [e["kind"] for e in detail.json()["events"]] == ["weather", "unknown:7"]


class TestRoundTrip:
    async def test_export_writes_events_and_reimports_losslessly(self, db_session):
        """Events survive export → .diary → parse with kinds intact."""
        from app.models.entry import Entry
        from app.models.entry_event import EntryEvent

        entry = Entry(
            entry_date=date(2026, 6, 12),
            title="Rainy day",
            body="Storm rolled in.",
        )
        db_session.add(entry)
        await db_session.flush()
        db_session.add_all(
            [
                EntryEvent(
                    entry_id=entry.id,
                    kind="weather",
                    content="84 / 74 °F",
                    label="Partly Cloudy",
                ),
                EntryEvent(entry_id=entry.id, kind="unknown:7", content="12,340"),
            ]
        )
        await db_session.commit()

        # Re-load with events eagerly: the export builder runs in a worker
        # thread, where a lazy relationship load would fail (no greenlet).
        from sqlalchemy.orm import selectinload

        from sqlalchemy import select

        loaded = (
            await db_session.execute(
                select(Entry)
                .options(selectinload(Entry.events))
                .where(Entry.id == entry.id)
            )
        ).scalar_one()
        data = await build_diarium_database([loaded])
        parsed = parse_diarium_sqlite(data)
        assert len(parsed) == 1
        assert parsed[0]["events"] == [
            {"kind": "weather", "content": "84 / 74 °F", "label": "Partly Cloudy"},
            {"kind": "unknown:7", "content": "12,340", "label": None},
        ]


class TestSchemaUpgrade:
    async def test_existing_db_gains_entry_events_on_boot(
        self, db_engine: AsyncEngine
    ):
        """The upgrade path: a DB created before the feature lacks the table;
        the boot-time ``create_all`` heals it without touching existing rows."""
        from app.core.database import Base

        async with db_engine.begin() as conn:
            await conn.execute(text("DROP TABLE entry_events"))
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) "
                    "VALUES ('2026-01-01', 'kept', 0, 0)"
                )
            )

        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with db_engine.connect() as conn:
            exists = (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='entry_events'"
                    )
                )
            ).scalar()
            kept = (await conn.execute(text("SELECT body FROM entries"))).scalar()
        assert exists == "entry_events"
        assert kept == "kept"  # existing data untouched

    async def test_legacy_table_cleanup_spares_entry_events(
        self, db_engine: AsyncEngine
    ):
        from app.core.database import _drop_removed_feature_tables

        async with db_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (x)"))
            await _drop_removed_feature_tables(conn)
            kept = (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='entry_events'"
                    )
                )
            ).scalar()
            dropped = (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='alembic_version'"
                    )
                )
            ).scalar()
        assert kept == "entry_events"
        assert dropped is None
