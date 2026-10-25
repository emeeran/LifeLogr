"""Tests for the "On this day" feature: endpoint, service, reminder injection.

Covers prior-year same-month/day matching, year-1 tick-epoch exclusion,
soft-deleted exclusion, leap-day surfacing (Feb 29 → Feb 28 on non-leap
years), and the reminder notification's memory-count line.
"""

from datetime import date
from unittest.mock import Mock

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.services.entry_service import EntryService

# Seeding goes through raw SQL so tests can insert dates the API can't produce
# (year 1) and don't depend on the create path's enrichment scheduling.
_INSERT = (
    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted, title, mood) "
    "VALUES (:d, 'body', :deleted, :encrypted, :title, :mood)"
)


async def _seed(
    db_engine: AsyncEngine,
    d: str,
    *,
    title: str | None = None,
    mood: str | None = None,
    deleted: int = 0,
    encrypted: int = 0,
) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(_INSERT),
            {"d": d, "title": title, "mood": mood, "deleted": deleted, "encrypted": encrypted},
        )


def _years_ago(n: int, *, today: date | None = None) -> str:
    """Same month/day, n years back (as an ISO string for seeding)."""
    t = today or date.today()
    return date(t.year - n, t.month, t.day).isoformat()


class TestOnThisDayEndpoint:
    async def test_same_date_multi_year(self, client: AsyncClient, db_engine: AsyncEngine):
        await _seed(db_engine, _years_ago(1), title="last year", mood="good")
        await _seed(db_engine, _years_ago(3), title="three years ago")
        await _seed(db_engine, _years_ago(0), title="today — must not appear")
        r = await client.get("/api/v1/entries/on-this-day")
        assert r.status_code == 200, r.text
        items = r.json()
        assert [i["title"] for i in items] == ["three years ago", "last year"]
        assert items[1]["mood"] == "good"

    async def test_empty_journal_returns_empty_list(self, client: AsyncClient):
        r = await client.get("/api/v1/entries/on-this-day")
        assert r.status_code == 200
        assert r.json() == []

    async def test_soft_deleted_excluded(self, client: AsyncClient, db_engine: AsyncEngine):
        await _seed(db_engine, _years_ago(2), title="gone", deleted=1)
        r = await client.get("/api/v1/entries/on-this-day")
        assert r.json() == []

    async def test_year_1_artifacts_excluded(
        self, client: AsyncClient, db_engine: AsyncEngine
    ):
        # .NET-tick-epoch rows imported from a Diarium backup land on 0001-01-01.
        await _seed(db_engine, "0001-01-01", title="tick epoch artifact")
        r = await client.get("/api/v1/entries/on-this-day")
        assert r.status_code == 200
        assert r.json() == []


class TestOnThisDayService:
    """Leap-day behaviour needs a fixed "today", so these drive the service
    directly rather than the endpoint (which uses the real clock)."""

    async def test_feb29_surfaces_on_feb28_of_non_leap_year(
        self, db_engine: AsyncEngine, db_session: AsyncSession
    ):
        await _seed(db_engine, "2024-02-29", title="leap day")  # 2024 is a leap year
        svc = EntryService(db_session)
        items = await svc.get_on_this_day(date(2025, 2, 28))  # 2025 is not
        assert [i.title for i in items] == ["leap day"]
        # ...and Feb 28 entries still match their own day.
        await _seed(db_engine, "2023-02-28", title="ordinary 28th")
        items = await EntryService(db_session).get_on_this_day(date(2025, 2, 28))
        assert sorted(i.title for i in items) == ["leap day", "ordinary 28th"]

    async def test_feb29_not_double_shown_on_mar_1(
        self, db_engine: AsyncEngine, db_session: AsyncSession
    ):
        await _seed(db_engine, "2024-02-29", title="leap day")
        items = await EntryService(db_session).get_on_this_day(date(2025, 3, 1))
        assert items == []

    async def test_feb29_stays_on_feb29_in_leap_years(
        self, db_engine: AsyncEngine, db_session: AsyncSession
    ):
        await _seed(db_engine, "2024-02-29", title="leap day")
        await _seed(db_engine, "2023-02-28", title="ordinary 28th")
        items = await EntryService(db_session).get_on_this_day(date(2028, 2, 29))
        assert [i.title for i in items] == ["leap day"]

    async def test_century_non_leap_year(
        self, db_engine: AsyncEngine, db_session: AsyncSession
    ):
        # 1900 is not a leap year (divisible by 100, not 400), so a Feb 29
        # entry from 1896 (leap) must surface on Feb 28, 1900.
        await _seed(db_engine, "1896-02-29", title="19th century leap day")
        items = await EntryService(db_session).get_on_this_day(date(1900, 2, 28))
        assert [i.title for i in items] == ["19th century leap day"]


class TestReminderMemoryLine:
    async def test_notification_includes_memory_count(
        self, db_engine: AsyncEngine, db_session: AsyncSession, monkeypatch
    ):
        from app.services import scheduler_service
        from app.services.reminder_service import ReminderService

        async with db_engine.begin() as conn:
            await conn.execute(
                text(_INSERT),
                {"d": _years_ago(1), "title": "memory", "mood": None,
                 "deleted": 0, "encrypted": 0},
            )
            result = await conn.execute(
                text(
                    "INSERT INTO reminders (title, reminder_time, days_of_week, is_active) "
                    "VALUES ('Write', '09:00:00', '1,2,3,4,5', 1)"
                )
            )
            reminder_id = result.lastrowid

        # _send_notification is sync and runs inside asyncio.to_thread, so a
        # plain Mock records the call (an AsyncMock's coroutine never awaited).
        send = Mock()
        monkeypatch.setattr(ReminderService, "_send_notification", send)

        await scheduler_service._fire_reminder(reminder_id=reminder_id, mark_fired=False)
        assert send.call_count == 1
        title, message = send.call_args.args
        assert "1 entry" in message and "on this day in past years" in message

    async def test_notification_without_memories_unchanged(
        self, db_engine: AsyncEngine, db_session: AsyncSession, monkeypatch
    ):
        from app.services import scheduler_service
        from app.services.reminder_service import ReminderService

        async with db_engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO reminders (title, reminder_time, days_of_week, is_active) "
                    "VALUES ('Write', '09:00:00', '1,2,3,4,5', 1)"
                )
            )
            reminder_id = result.lastrowid

        send = Mock()
        monkeypatch.setattr(ReminderService, "_send_notification", send)
        await scheduler_service._fire_reminder(reminder_id=reminder_id, mark_fired=False)
        title, message = send.call_args.args
        assert "past years" not in message
        assert message == "Time to write in your journal!"
