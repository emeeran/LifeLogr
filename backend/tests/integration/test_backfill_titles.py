"""Maintenance: backfill empty entry titles from the body's first line."""

from __future__ import annotations

from datetime import date

from httpx import AsyncClient
from sqlalchemy import select

from app.models.entry import Entry


async def _seed(db_session, day: date, body: str, title: str | None = None) -> Entry:
    entry = Entry(entry_date=day, body=body, title=title, mood=None)
    db_session.add(entry)
    await db_session.commit()
    return entry


async def test_dry_run_reports_candidates_without_writing(
    client: AsyncClient, db_session
) -> None:
    entry = await _seed(db_session, date(2026, 1, 2), "# A real first line\n\nBody.")
    await _seed(db_session, date(2026, 1, 3), "Has a title already.", title="Kept")
    await _seed(db_session, date(2026, 1, 4), "![](/api/v1/media/1/file)")

    r = await client.post("/api/v1/entries/backfill-titles")
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["candidates"] == 1
    assert body["updated"] == 0
    assert body["samples"] == [{"id": entry.id, "title": "A real first line"}]

    refreshed = await db_session.get(Entry, entry.id)
    assert refreshed.title is None


async def test_apply_fills_only_empty_titles(
    client: AsyncClient, db_session
) -> None:
    first = await _seed(db_session, date(2026, 2, 1), "- bought tickets")
    titled = await _seed(db_session, date(2026, 2, 2), "Text.", title="Mine")
    photo = await _seed(db_session, date(2026, 2, 3), "![Sunset](x.jpg)")
    empty = await _seed(db_session, date(2026, 2, 4), "   ")

    r = await client.post("/api/v1/entries/backfill-titles", params={"dry_run": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 2  # "- bought tickets" and the image alt text

    # Scalar column reads after the request's session committed: no lazy
    # attribute refresh (which would need a greenlet outside the loop).
    titles = dict((await db_session.execute(select(Entry.id, Entry.title))).all())
    assert titles[first.id] == "bought tickets"
    assert titles[titled.id] == "Mine"
    assert titles[photo.id] == "Sunset"
    assert titles[empty.id] is None


async def test_backfill_refreshes_the_sync_fingerprint(
    client: AsyncClient, db_session
) -> None:
    """A backfilled title must not read as a local edit to the next Diarium pull."""
    entry = await _seed(db_session, date(2026, 3, 1), "hello world")
    entry.sync_hash = "stale-hash"
    await db_session.commit()

    await client.post(
        "/api/v1/entries/backfill-titles", params={"dry_run": "false"}
    )
    row = (
        await db_session.execute(
            select(Entry.title, Entry.sync_hash).where(Entry.id == entry.id)
        )
    ).one()
    assert row.title == "hello world"
    assert row.sync_hash != "stale-hash"
