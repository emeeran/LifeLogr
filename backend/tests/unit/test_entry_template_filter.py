"""Tests for the Timeline template filter: entry↔template link + filtering.

Covers: creating an entry from a template records ``template_id``, the list
endpoint filters by it, and the one-time content-match backfill links legacy
entries. ``ON DELETE SET NULL`` is enforced by the SQLite FK pragma in
production (the test engine doesn't enable FK), so it's verified manually
rather than here.
"""

from datetime import date  # noqa: F401  (kept for readability of entry fixtures)
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.database import _backfill_entry_templates


async def _template(client: AsyncClient, name: str, body: str) -> dict:
    r = await client.post("/api/v1/templates", json={"name": name, "body": body})
    assert r.status_code == 201, r.text
    return r.json()


class TestEntryTemplateLink:
    async def test_create_entry_records_template_id(self, client: AsyncClient):
        tmpl = await _template(client, "Morning", "Grateful for:\n\nIntentions:\n\n")
        r = await client.post(
            "/api/v1/entries",
            json={"entry_date": "2026-05-08", "body": "x", "template_id": tmpl["id"]},
        )
        assert r.status_code == 201, r.text
        assert r.json()["template_id"] == tmpl["id"]

    async def test_create_without_template_is_null(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-08", "body": "x"})
        assert r.status_code == 201
        assert r.json()["template_id"] is None

    async def test_list_filter_by_template_id(self, client: AsyncClient):
        a = await _template(client, "A", "Template A structured body content")
        b = await _template(client, "B", "Template B structured body content")
        e_a = (
            await client.post(
                "/api/v1/entries",
                json={"entry_date": "2026-05-01", "body": "a", "template_id": a["id"]},
            )
        ).json()
        e_b = (
            await client.post(
                "/api/v1/entries",
                json={"entry_date": "2026-05-02", "body": "b", "template_id": b["id"]},
            )
        ).json()
        e_none = (
            await client.post("/api/v1/entries", json={"entry_date": "2026-05-03", "body": "c"})
        ).json()

        r = await client.get("/api/v1/entries", params={"template_id": a["id"]})
        assert r.status_code == 200
        ids = {it["id"] for it in r.json()["items"]}
        assert e_a["id"] in ids
        assert e_b["id"] not in ids
        assert e_none["id"] not in ids

    async def test_list_without_filter_returns_all(self, client: AsyncClient):
        a = await _template(client, "C", "Template C structured body content")
        await client.post(
            "/api/v1/entries",
            json={"entry_date": "2026-05-01", "body": "a", "template_id": a["id"]},
        )
        await client.post("/api/v1/entries", json={"entry_date": "2026-05-02", "body": "freeform"})
        r = await client.get("/api/v1/entries")
        assert r.json()["total"] >= 2


class TestEntryTemplateBackfill:
    async def test_links_entries_whose_body_starts_with_a_template(self, db_engine: AsyncEngine):
        body = "Grateful for:\n\nIntentions for today:\n\n"
        async with db_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO templates (name, body, is_builtin) VALUES ('Morning', :b, 0)"),
                {"b": body},
            )
            tid = (
                await conn.execute(text("SELECT id FROM templates WHERE name = 'Morning'"))
            ).scalar_one()
            # One entry created from the template (body = template + additions)...
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2026-01-01', :b, 0, 0)"
                ),
                {"b": body + "extra freeform writing"},
            )
            # ...and one freeform entry that doesn't match.
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2026-01-02', :b, 0, 0)"
                ),
                {"b": "totally unrelated freeform entry"},
            )
            await _backfill_entry_templates(conn)
            matched = (
                await conn.execute(
                    text("SELECT template_id FROM entries WHERE entry_date = '2026-01-01'")
                )
            ).scalar_one()
            unmatched = (
                await conn.execute(
                    text("SELECT template_id FROM entries WHERE entry_date = '2026-01-02'")
                )
            ).scalar_one()
        assert matched == tid
        assert unmatched is None

    async def test_prefers_longest_matching_template(self, db_engine: AsyncEngine):
        short = "Daily check-in:\n\n"  # 17 chars — a valid candidate
        long_body = "Daily check-in:\n\nDetailed mood:\n\nGoals:\n\n"
        async with db_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO templates (name, body, is_builtin) VALUES ('Short', :b, 0)"),
                {"b": short},
            )
            await conn.execute(
                text("INSERT INTO templates (name, body, is_builtin) VALUES ('Long', :b, 0)"),
                {"b": long_body},
            )
            long_id = (
                await conn.execute(text("SELECT id FROM templates WHERE name = 'Long'"))
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2026-02-01', :b, 0, 0)"
                ),
                {"b": long_body + "extra"},
            )
            await _backfill_entry_templates(conn)
            matched = (
                await conn.execute(
                    text("SELECT template_id FROM entries WHERE entry_date = '2026-02-01'")
                )
            ).scalar_one()
        # Both templates match by prefix; the longer (most specific) wins.
        assert matched == long_id

    async def test_ignores_short_template_bodies(self, db_engine: AsyncEngine):
        async with db_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO templates (name, body, is_builtin) VALUES ('Tiny', :b, 0)"),
                {"b": "hi"},  # < 15 chars → not a candidate
            )
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) VALUES ('2026-03-01', :b, 0, 0)"
                ),
                {"b": "hi there"},
            )
            await _backfill_entry_templates(conn)
            tid = (
                await conn.execute(
                    text("SELECT template_id FROM entries WHERE entry_date = '2026-03-01'")
                )
            ).scalar_one()
        assert tid is None
