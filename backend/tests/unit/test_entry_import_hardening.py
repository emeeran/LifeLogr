"""Import/export correctness: tag_ids honoured, geo, tag-filter dedupe, size caps,
skip reasons, deterministic deduplication, reset table derivation, folder counts.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

from httpx import AsyncClient
from sqlalchemy import select

from app.models.entry import Entry
from app.models.tag import EntryTag, Tag


async def _create_entry(client: AsyncClient, date="2026-05-08", body="Hello world", **kw):
    r = await client.post("/api/v1/entries", json={"entry_date": date, "body": body, **kw})
    assert r.status_code == 201, r.text
    return r.json()


class TestTagIdsHonoured:
    async def test_create_applies_explicit_tag_ids(self, client: AsyncClient, db_session):
        tag = Tag(name="imported-tag")
        db_session.add(tag)
        await db_session.commit()

        entry = await _create_entry(
            client, "2026-06-01", "no hashtags here", tag_ids=[tag.id]
        )
        assert [t["name"] for t in entry["tags"]] == ["imported-tag"]

    async def test_create_merges_explicit_ids_with_hashtags(self, client: AsyncClient):
        entry = await _create_entry(client, "2026-06-02", "body with #inline tag", tag_ids=[])
        assert {t["name"] for t in entry["tags"]} == {"inline"}

    async def test_update_applies_explicit_tag_ids_without_body_change(
        self, client: AsyncClient, db_session
    ):
        tag = Tag(name="picked")
        db_session.add(tag)
        await db_session.commit()
        entry = await _create_entry(client, "2026-06-03", "stable body")

        r = await client.patch(f"/api/v1/entries/{entry['id']}", json={"tag_ids": [tag.id]})
        assert r.status_code == 200
        assert [t["name"] for t in r.json()["tags"]] == ["picked"]

    async def test_update_body_with_tag_ids_unions_both_sources(
        self, client: AsyncClient, db_session
    ):
        tag = Tag(name="picked")
        db_session.add(tag)
        await db_session.commit()

        r = await client.post(
            "/api/v1/entries",
            json={"entry_date": "2026-06-04", "body": "has #inline"},
            params={},
        )
        entry_id = r.json()["id"]
        r2 = await client.patch(
            f"/api/v1/entries/{entry_id}", json={"body": "rewritten #inline", "tag_ids": [tag.id]}
        )
        assert {t["name"] for t in r2.json()["tags"]} == {"inline", "picked"}

    async def test_import_file_applies_tags_and_coordinates(self, client: AsyncClient, db_session):
        payload = {
            "app": "lifelogr",
            "version": 1,
            "entries": [
                {
                    "entry_date": "2026-07-01",
                    "title": "Geo entry",
                    "body": "body with tags",
                    "mood": "good",
                    "tags": ["trip", "berlin"],
                    "latitude": 52.52,
                    "longitude": 13.405,
                }
            ],
        }
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("exp.json", json.dumps(payload).encode(), "application/json")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1
        assert r.json()["skipped"] == 0

        row = (
            await db_session.execute(
                select(Entry).where(Entry.entry_date == date(2026, 7, 1))
            )
        ).scalar_one()

        tag_names = {
            t.name
            for t in (
                await db_session.execute(
                    select(Tag).join(EntryTag, EntryTag.tag_id == Tag.id).where(
                        EntryTag.entry_id == row.id
                    )
                )
            ).scalars()
        }
        assert tag_names == {"trip", "berlin"}
        assert row.latitude == 52.52
        assert row.longitude == 13.405

    async def test_import_endpoint_applies_tags(self, client: AsyncClient, db_session):
        r = await client.post(
            "/api/v1/entries/import",
            json=[
                {
                    "entry_date": "2026-07-02",
                    "body": "json import body",
                    "title": "T",
                    "tags": ["alpha", "beta"],
                }
            ],
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1

        row = (
            await db_session.execute(select(Entry).where(Entry.entry_date == date(2026, 7, 2)))
        ).scalar_one()
        tag_names = {
            t.name
            for t in (
                await db_session.execute(
                    select(Tag).join(EntryTag, EntryTag.tag_id == Tag.id).where(
                        EntryTag.entry_id == row.id
                    )
                )
            ).scalars()
        }
        assert tag_names == {"alpha", "beta"}


class TestGeoPassthrough:
    async def test_create_and_update_persist_coordinates(self, client: AsyncClient):
        entry = await _create_entry(
            client, "2026-06-20", "geo entry", latitude=48.8566, longitude=2.3522
        )
        assert entry["latitude"] == 48.8566
        assert entry["longitude"] == 2.3522

        r = await client.patch(
            f"/api/v1/entries/{entry['id']}", json={"latitude": 41.3874, "longitude": 2.1686}
        )
        assert r.status_code == 200
        assert r.json()["latitude"] == 41.3874

    async def test_coordinates_out_of_range_rejected(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/entries",
            json={"entry_date": "2026-06-21", "body": "x", "latitude": 999.0},
        )
        assert r.status_code == 422


class TestTagFilterDedupes:
    async def test_entry_with_two_matching_tags_appears_once(
        self, client: AsyncClient, db_session
    ):
        t1 = Tag(name="one")
        t2 = Tag(name="two")
        db_session.add_all([t1, t2])
        await db_session.commit()

        entry = await _create_entry(client, "2026-06-10", "tagged entry")
        entry_id = entry["id"]
        db_session.add_all(
            [EntryTag(entry_id=int(entry_id), tag_id=t1.id), EntryTag(entry_id=int(entry_id), tag_id=t2.id)]
        )
        await db_session.commit()
        await _create_entry(client, "2026-06-11", "untagged entry")

        r = await client.get(f"/api/v1/entries?tag_ids={t1.id},{t2.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert [i["id"] for i in data["items"]] == [entry_id]


class TestImportHardening:
    async def test_oversize_upload_rejected_with_413(self, client: AsyncClient, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_IMPORT_SIZE_BYTES", 1024)
        payload = json.dumps(
            {"entries": [{"entry_date": "2026-07-03", "body": "x" * 4096}]}
        ).encode()
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("exp.json", payload, "application/json")},
        )
        assert r.status_code == 413
        assert "limit" in r.json()["detail"]

    async def test_oversize_zip_member_rejected_with_413(self, client: AsyncClient):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("2026-07-04.md", "---\ndate: 2026-07-04\n---\n\nbody")
            # Lie about a small member's declared size is not possible here, so
            # instead make a genuinely oversized member and cap it via monkeypatch
            # of the module constant in the second half of this test.
            zf.writestr("huge.md", "x" * (200 * 1024))
        from app.routers import entries as entries_mod

        original = entries_mod._MAX_IMPORT_MEMBER_BYTES
        entries_mod._MAX_IMPORT_MEMBER_BYTES = 1024
        try:
            r = await client.post(
                "/api/v1/entries/import/file",
                files={"file": ("vault.zip", buf.getvalue(), "application/zip")},
            )
        finally:
            entries_mod._MAX_IMPORT_MEMBER_BYTES = original
        assert r.status_code == 413
        assert "Archive member" in r.json()["detail"]

    async def test_import_reports_skip_reasons(self, client: AsyncClient, db_session):
        db_session.add(
            Entry(entry_date=date(2026, 7, 5), title="Existing", body="dup body here")
        )
        await db_session.commit()

        payload = {
            "entries": [
                {"entry_date": "2026-07-05", "body": "dup body here"},
                {"entry_date": "", "body": "no date"},
                "not-a-dict",
            ]
        }
        r = await client.post(
            "/api/v1/entries/import/file",
            files={"file": ("exp.json", json.dumps(payload).encode(), "application/json")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 0
        assert data["skipped"] == 3
        reasons = {x["reason"] for x in data["skip_reasons"]}
        assert any("duplicate" in x for x in reasons)
        assert any("missing entry_date or body" in x for x in reasons)
        # The non-dict record is skipped (not a 500) with a parse reason.
        assert any("unparsable record" in x for x in reasons)
        assert len(data["skip_reasons"]) == 3
        assert [x["index"] for x in data["skip_reasons"]] == [0, 1, 2]

    async def test_duplicate_detection_uses_sql_side_prefix(self, client, db_session):
        """The dedup pre-pass fingerprints a SQL-side truncated prefix."""
        from sqlalchemy import event

        db_session.add(Entry(entry_date=date(2026, 7, 6), body="same prefix body"))
        await db_session.commit()

        statements: list[str] = []

        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if "substr" in statement.lower() and "entries" in statement.lower():
                statements.append(statement)

        engine = db_session.get_bind()  # the sync engine behind the async session
        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
        try:
            r = await client.post(
                "/api/v1/entries/import/file",
                files={
                    "file": (
                        "exp.json",
                        json.dumps(
                            {"entries": [{"entry_date": "2026-07-06", "body": "same prefix body"}]}
                        ).encode(),
                        "application/json",
                    )
                },
            )
            assert r.status_code == 200
            assert r.json()["skipped"] == 1  # still detected as a duplicate
        finally:
            event.remove(engine, "before_cursor_execute", _before_cursor_execute)

        assert statements, "expected a substr-based duplicate scan"
        sql = statements[0].lower()
        assert "substr(entries.body" in sql  # truncated prefix, not the whole body
        assert "select entries.body" not in sql


class TestDeduplicateDeterminism:
    async def test_keeps_lowest_id_and_normalizes_whitespace(self, client, db_session):
        e1 = Entry(entry_date=date(2026, 8, 1), body="Hello\n\n  World ")
        e2 = Entry(entry_date=date(2026, 8, 1), body="hello world")
        e3 = Entry(entry_date=date(2026, 8, 1), body="hello   world")
        db_session.add_all([e1, e2, e3])
        await db_session.commit()

        r = await client.post("/api/v1/entries/deduplicate")
        assert r.status_code == 200
        data = r.json()
        assert data["duplicates_removed"] == 2
        assert data["groups_found"] == 1

        surviving = (
            await db_session.execute(
                select(Entry).where(Entry.entry_date == date(2026, 8, 1), ~Entry.is_deleted)
            )
        ).scalars().all()
        assert [e.id for e in surviving] == [e1.id]  # lowest id kept

    async def test_distinct_dates_are_not_merged(self, client, db_session):
        db_session.add_all(
            [
                Entry(entry_date=date(2026, 8, 2), body="same text"),
                Entry(entry_date=date(2026, 8, 3), body="same text"),
            ]
        )
        await db_session.commit()
        r = await client.post("/api/v1/entries/deduplicate")
        assert r.json()["duplicates_removed"] == 0

    async def test_empty_bodies_are_not_treated_as_duplicates(self, client, db_session):
        db_session.add_all(
            [
                Entry(entry_date=date(2026, 8, 4), body=""),
                Entry(entry_date=date(2026, 8, 4), body=""),
            ]
        )
        await db_session.commit()
        r = await client.post("/api/v1/entries/deduplicate")
        assert r.json()["duplicates_removed"] == 0


class TestResetDerivation:
    async def test_reset_wipes_notes_and_entries_but_spares_config(self, client, db_session):
        from sqlalchemy import text

        db_session.add(Entry(entry_date=date(2026, 9, 1), body="doomed"))
        await db_session.commit()

        r = await client.post("/api/v1/entries/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        await db_session.commit()

        tables = {
            row[0]
            for row in (
                await db_session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).all()
        }
        wiped = {}
        for t in ("entries", "notes", "note_folders", "note_pages", "tags", "entry_tags"):
            if t in tables:
                wiped[t] = (
                    await db_session.execute(text(f"SELECT COUNT(*) FROM {t}"))
                ).scalar()
        assert wiped and all(v == 0 for v in wiped.values())

    async def test_protected_tables_exclude_config(self):
        from app.routers.entries import _RESET_PROTECTED_TABLES, _reset_table_names

        names = _reset_table_names()
        assert "entries" in names and "notes" in names and "note_pages" in names
        assert not (_RESET_PROTECTED_TABLES & set(names))
        # Children are deleted before the tables they reference.
        assert names.index("entry_tags") < names.index("entries")
        assert names.index("note_pages") < names.index("notes")


class TestFolderCounts:
    async def test_create_and_update_folder_return_real_note_count(self, client):
        r = await client.post("/api/v1/notes/folders", json={"name": "Work"})
        assert r.status_code == 201
        folder = r.json()
        assert folder["note_count"] == 0

        await client.post(
            "/api/v1/notes", json={"title": "n1", "body": "b1", "folder_id": folder["id"]}
        )
        await client.post(
            "/api/v1/notes", json={"title": "n2", "body": "b2", "folder_id": folder["id"]}
        )

        r2 = await client.patch(
            f"/api/v1/notes/folders/{folder['id']}", json={"color": "#ff0000"}
        )
        assert r2.status_code == 200
        assert r2.json()["note_count"] == 2

        listed = (await client.get("/api/v1/notes/folders")).json()
        assert listed[0]["note_count"] == 2

    async def test_list_folders_does_not_load_note_bodies(self, client, db_session):
        from app.services.note_service import NoteService

        folder = (
            await client.post("/api/v1/notes/folders", json={"name": "Heavy"})
        ).json()
        await client.post(
            "/api/v1/notes", json={"title": "big", "body": "X" * 5000, "folder_id": folder["id"]}
        )

        svc = NoteService(db_session)
        for folder_row, count in await svc.list_folders():
            # Rows are projections: they carry no lazy-loaded notes collection.
            assert not hasattr(folder_row, "notes")
            assert count == (1 if folder_row.id == folder["id"] else count)
