"""Diarium tag trackers (Tags.Type=2 + EntryTags.TrackingValue) import.

Fixture-driven (no tracker tags exist in the reference backup): covers the
parser carrying readings verbatim, persistence (is_tracker flag + per-entry
tracking_value), the API surface, and the column-migration upgrade path.
"""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.importers.diarium import parse_diarium_sqlite
from tests.helpers.diarium_diary import build_diary


def _fixture_diary() -> bytes:
    return build_diary(
        [
            {
                "date": "2026-06-12",
                "text": "Tracked day",
                "tags": ["walk", "weight", "mood-log"],
                "tag_types": [0, 2, 2],
                "tracking": [None, "72.5", "true"],
            },
            {
                # Same tracker, no reading that day (TrackingValue NULL).
                "date": "2026-06-13",
                "text": "Rest day",
                "tags": ["weight"],
                "tag_types": [2],
            },
        ]
    )


class TestParse:
    def test_trackers_parse_verbatim_and_plain_tags_exclude_them(self):
        entries = parse_diarium_sqlite(_fixture_diary())
        assert len(entries) == 2
        first, second = entries
        # Plain tag stays in tags; trackers carry their verbatim readings.
        assert first["tags"] == ["walk"]
        assert first["trackers"] == [
            {"name": "weight", "value": "72.5"},
            {"name": "mood-log", "value": "true"},
        ]
        # NULL TrackingValue imports as a tracker with no reading.
        assert second["tags"] == []
        assert second["trackers"] == [{"name": "weight", "value": None}]

    def test_pre_type_column_database_imports_without_trackers(self):
        # Ancient schema: Tags lacks Type and EntryTags lacks TrackingValue —
        # everything imports as plain tags, no crash.
        import sqlite3
        import tempfile
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.executescript(
            "CREATE TABLE Entries (DiaryEntryId bigint primary key, Heading varchar, "
            "Text varchar, Rating integer, Latitude float, Longitude float);"
            "CREATE TABLE Tags (DiaryTagId integer primary key, Value varchar);"
            "CREATE TABLE EntryTags (DiaryEntryId bigint, DiaryTagId integer);"
        )
        conn.execute(
            "INSERT INTO Entries VALUES (1, '', 'old', 0, 0, 0)"
        )
        conn.execute("INSERT INTO Tags VALUES (1, 'ancient')")
        conn.execute("INSERT INTO EntryTags VALUES (1, 1)")
        conn.commit()
        conn.close()
        data = Path(tmp.name).read_bytes()
        Path(tmp.name).unlink()
        entries = parse_diarium_sqlite(data)
        assert entries[0]["tags"] == ["ancient"]
        assert entries[0]["trackers"] == []


class TestImport:
    async def test_import_flags_tracker_tags_and_stamps_readings(
        self, client: AsyncClient, db_engine: AsyncEngine
    ):
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("backup.diary", _fixture_diary(), "application/octet-stream")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 2

        async with db_engine.connect() as conn:
            trackers = (
                await conn.execute(
                    text(
                        "SELECT t.name, t.is_tracker, et.entry_id, et.tracking_value "
                        "FROM tags t JOIN entry_tags et ON et.tag_id = t.id "
                        "WHERE t.is_tracker = 1 ORDER BY et.entry_id, t.name"
                    )
                )
            ).all()
            plain = (
                await conn.execute(
                    text("SELECT name FROM tags WHERE is_tracker = 0")
                )
            ).scalars().all()
        assert plain == ["walk"]
        # 'weight' spans both entries (one reading, one NULL); 'mood-log' on the first.
        assert [(n, e, v) for n, _, e, v in trackers] == [
            ("mood-log", 1, "true"),
            ("weight", 1, "72.5"),
            ("weight", 2, None),
        ]

        detail = await client.get("/api/v1/entries/1")
        assert detail.status_code == 200
        by_name = {t["name"]: t for t in detail.json()["tags"]}
        assert by_name["weight"]["is_tracker"] is True
        assert by_name["weight"]["tracking_value"] == "72.5"
        assert by_name["walk"]["tracking_value"] is None

    async def test_tag_tree_exposes_is_tracker(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("backup.diary", _fixture_diary(), "application/octet-stream")},
        )
        tree = (await client.get("/api/v1/tags/tree")).json()
        trackers = {t["name"]: t["is_tracker"] for t in tree}
        assert trackers["weight"] is True
        assert trackers["walk"] is False


class TestSchemaUpgrade:
    async def test_column_migrations_restore_tracker_columns(
        self, db_engine: AsyncEngine
    ):
        """A DB created before the feature lacks both columns; the boot-time
        column migrations add them back without touching existing rows."""
        from app.core.database import _migrate_schema

        async with db_engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE entry_tags DROP COLUMN tracking_value")
            )
            await conn.execute(text("ALTER TABLE tags DROP COLUMN is_tracker"))
            await conn.execute(
                text(
                    "INSERT INTO tags (name) VALUES ('legacy')"
                )
            )

        async with db_engine.begin() as conn:
            await _migrate_schema(conn)

        async with db_engine.connect() as conn:
            tag_cols = {
                r[1]
                for r in (
                    await conn.execute(text("PRAGMA table_info(tags)"))
                ).fetchall()
            }
            assoc_cols = {
                r[1]
                for r in (
                    await conn.execute(text("PRAGMA table_info(entry_tags)"))
                ).fetchall()
            }
            name = (await conn.execute(text("SELECT name FROM tags"))).scalar()
        assert "is_tracker" in tag_cols
        assert "tracking_value" in assoc_cols
        assert name == "legacy"
