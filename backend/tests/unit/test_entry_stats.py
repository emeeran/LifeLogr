"""Tests for the journal stats aggregates (GET /api/v1/entries/stats).

Covers streaks (current + longest), total words (shared word-count
definition), the zero-filled weekly histogram, mood/media distributions,
empty-journal zeros, and the in-memory cache (hit + invalidation on write).
"""

from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.entry_service import (
    EntryService,
    invalidate_stats_cache,
)

_INSERT = (
    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted, mood) "
    "VALUES (:d, :b, :deleted, :encrypted, :mood)"
)


async def _seed(
    db_engine: AsyncEngine,
    d: str,
    *,
    body: str = "body",
    mood: str | None = None,
    deleted: int = 0,
    encrypted: int = 0,
) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(_INSERT),
            {"d": d, "b": body, "mood": mood, "deleted": deleted, "encrypted": encrypted},
        )


def _iso(d: date) -> str:
    return d.isoformat()


class TestStreaks:
    async def test_streak_ending_yesterday_still_counts(
        self, db_engine: AsyncEngine, db_session
    ):
        today = date.today()
        await _seed(db_engine, _iso(today - timedelta(days=1)))
        await _seed(db_engine, _iso(today - timedelta(days=2)))
        stats = await EntryService(db_session).get_stats()
        assert stats.current_streak == 2

    async def test_streak_includes_today(self, db_engine: AsyncEngine, db_session):
        today = date.today()
        await _seed(db_engine, _iso(today))
        await _seed(db_engine, _iso(today - timedelta(days=1)))
        await _seed(db_engine, _iso(today - timedelta(days=2)))
        stats = await EntryService(db_session).get_stats()
        assert stats.current_streak == 3

    async def test_gap_breaks_current_streak(
        self, db_engine: AsyncEngine, db_session
    ):
        today = date.today()
        await _seed(db_engine, _iso(today))
        await _seed(db_engine, _iso(today - timedelta(days=3)))
        stats = await EntryService(db_session).get_stats()
        assert stats.current_streak == 1
        assert stats.longest_streak == 1

    async def test_longest_streak_spans_history(
        self, db_engine: AsyncEngine, db_session
    ):
        base = date(2024, 3, 1)
        for i in range(5):  # a 5-day run in the past
            await _seed(db_engine, _iso(base + timedelta(days=i)))
        stats = await EntryService(db_session).get_stats()
        assert stats.longest_streak == 5
        assert stats.current_streak == 0  # nothing near today

    async def test_multiple_entries_same_day_count_once(
        self, db_engine: AsyncEngine, db_session
    ):
        today = date.today()
        await _seed(db_engine, _iso(today), body="a")
        await _seed(db_engine, _iso(today), body="b")
        stats = await EntryService(db_session).get_stats()
        assert stats.current_streak == 1
        assert stats.total_entries == 2


class TestAggregates:
    async def test_total_words_excludes_encrypted_and_deleted(
        self, db_engine: AsyncEngine, db_session
    ):
        await _seed(db_engine, "2026-01-01", body="one two  three\nfour")  # 4 words
        await _seed(db_engine, "2026-01-02", body="some more words here")  # 4
        await _seed(db_engine, "2026-01-03", body="cipher text", encrypted=1)
        await _seed(db_engine, "2026-01-04", body="gone", deleted=1)
        stats = await EntryService(db_session).get_stats()
        assert stats.total_words == 8
        assert stats.total_entries == 3  # deleted excluded, encrypted still an entry

    async def test_weekly_histogram_zero_filled_trailing_window(
        self, db_engine: AsyncEngine, db_session
    ):
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        await _seed(db_engine, _iso(this_monday), body="a")
        await _seed(db_engine, _iso(this_monday + timedelta(days=1)), body="b")
        await _seed(db_engine, _iso(this_monday - timedelta(weeks=2)), body="c")
        stats = await EntryService(db_session).get_stats(weeks=12)
        assert [w.count for w in stats.weekly] == [0] * 9 + [1, 0, 2]
        assert stats.weekly[-1].week_start == this_monday
        assert stats.weekly[0].week_start == this_monday - timedelta(weeks=11)

    async def test_mood_and_media_distributions(
        self, db_engine: AsyncEngine, db_session
    ):
        await _seed(db_engine, "2026-01-01", mood="good")
        await _seed(db_engine, "2026-01-02", mood="good")
        await _seed(db_engine, "2026-01-03", mood="awful")
        await _seed(db_engine, "2026-01-04", mood=None)
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO media (entry_id, filename, media_type, file_size, "
                    "storage_path, is_inline) "
                    "VALUES (1, 'a.jpg', 'image', 10, 'images/a.jpg', 0),"
                    "(1, 'b.jpg', 'image', 10, 'images/b.jpg', 0),"
                    "(2, 'c.mp4', 'video', 10, 'videos/c.mp4', 0)"
                )
            )
        stats = await EntryService(db_session).get_stats()
        assert {m.mood: m.count for m in stats.moods} == {"good": 2, "awful": 1}
        assert {m.media_type: m.count for m in stats.media} == {"image": 2, "video": 1}


class TestEndpoint:
    async def test_empty_journal_is_all_zeros(self, client: AsyncClient):
        r = await client.get("/api/v1/entries/stats")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_entries"] == 0
        assert body["total_words"] == 0
        assert body["current_streak"] == 0
        assert body["longest_streak"] == 0
        assert len(body["weekly"]) == 12
        assert all(w["count"] == 0 for w in body["weekly"])
        assert body["moods"] == []
        assert body["media"] == []

    async def test_endpoint_reports_seeded_data(
        self, client: AsyncClient, db_engine: AsyncEngine
    ):
        today = date.today()
        await _seed(db_engine, _iso(today), body="hello world", mood="great")
        r = await client.get("/api/v1/entries/stats")
        body = r.json()
        assert body["total_entries"] == 1
        assert body["total_words"] == 2
        assert body["current_streak"] == 1
        assert body["moods"] == [{"mood": "great", "count": 1}]

    async def test_cache_hit_and_invalidation(
        self, client: AsyncClient, db_engine: AsyncEngine, db_session
    ):
        r1 = (await client.get("/api/v1/entries/stats")).json()
        await _seed(db_engine, "2026-01-01", body="stale cache should not see me")
        # Cached value survives (TTL window) ...
        r2 = (await client.get("/api/v1/entries/stats")).json()
        assert r2["total_entries"] == r1["total_entries"]
        # ... until a mutation invalidates it.
        invalidate_stats_cache()
        r3 = (await client.get("/api/v1/entries/stats")).json()
        assert r3["total_entries"] == r2["total_entries"] + 1
