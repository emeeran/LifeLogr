"""Unit tests for two-way Google Calendar + Tasks sync (mocked Google API)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.security import encrypt
from app.models.google_sync import GoogleSyncAccount
from app.models.schedule_event import ScheduleEvent
from app.services.calendar_sync_service import (
    CalendarSyncService,
    _google_to_local,
    _rrule_from_google,
    _rrule_to_google,
)
from app.services.tasks_sync_service import TasksSyncService


class FakeResponse:
    def __init__(self, payload: dict | list, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> dict | list:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type])


class FakeAPI:
    """Stand-in for GoogleAPIClient that records requests and returns scripted JSON."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._script: dict[str, FakeResponse] = {}

    def script(self, key: str, payload: dict | list, status: int = 200) -> None:
        self._script[key] = FakeResponse(payload, status)

    async def request(self, method, url, *, params=None, json_body=None, headers=None, timeout=20.0, if_match=None):  # type: ignore[no-untyped-def]
        rec = {"method": method, "url": url, "json_body": json_body, "if_match": if_match}
        self.calls.append(rec)
        # Match the longest scripted key contained in the url.
        for key, resp in self._script.items():
            if key in url:
                return resp
        return FakeResponse({})

    async def __aenter__(self) -> FakeAPI:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass


def _all_day_event(eid: str, title: str, etag: str = "etag1") -> dict:
    return {
        "id": eid,
        "etag": etag,
        "status": "confirmed",
        "summary": title,
        "start": {"date": "2026-07-20"},
        "end": {"date": "2026-07-21"},
        "location": "Home",
        "description": "desc",
    }


@pytest.mark.asyncio
async def test_apply_event_creates_then_updates_no_duplicate(db_session):
    api = FakeAPI()
    svc = CalendarSyncService(db_session, GoogleSyncAccount(credentials_encrypted="x"), api)
    ev = _all_day_event("g1", "Lunch")

    await svc._apply_event(ev, "primary")
    await db_session.commit()
    rows = (await db_session.execute(select(ScheduleEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "google"
    assert rows[0].external_id == "g1"
    assert rows[0].title == "Lunch"
    assert rows[0].all_day is True
    assert rows[0].start_at == datetime(2026, 7, 20, 0, 0)

    # Re-apply (e.g. incremental re-pull) — update in place, no duplicate.
    ev["summary"] = "Brunch"
    ev["etag"] = "etag2"
    await svc._apply_event(ev, "primary")
    await db_session.commit()
    rows = (await db_session.execute(select(ScheduleEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Brunch"
    assert rows[0].etag == "etag2"
    # synced_at kept even with the just-pulled row (not seen as changed).
    assert rows[0].synced_at == rows[0].updated_at


@pytest.mark.asyncio
async def test_apply_event_cancellation_soft_deletes(db_session):
    api = FakeAPI()
    svc = CalendarSyncService(db_session, GoogleSyncAccount(credentials_encrypted="x"), api)
    await svc._apply_event(_all_day_event("g2", "Meet"), "primary")
    await db_session.commit()
    assert (
        await db_session.scalar(
            select(ScheduleEvent).where(ScheduleEvent.external_id == "g2")
        )
    ).is_deleted is False

    await svc._apply_event({"id": "g2", "status": "cancelled"}, "primary")
    await db_session.commit()
    row = await db_session.scalar(
        select(ScheduleEvent).where(ScheduleEvent.external_id == "g2")
    )
    assert row.is_deleted is True
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_push_patches_with_etag_and_marks_synced(db_session):
    api = FakeAPI()
    api.script("events/g3", {"etag": "etag-new"})
    acct = GoogleSyncAccount(credentials_encrypted="x", calendar_enabled=True, calendar_sync_token="t")
    svc = CalendarSyncService(db_session, acct, api)

    # Seed a synced event, then locally edit it (bump updated_at past synced_at).
    await svc._apply_event(_all_day_event("g3", "Old", etag="etag-old"), "primary")
    await db_session.commit()
    row = await db_session.scalar(
        select(ScheduleEvent).where(ScheduleEvent.external_id == "g3")
    )
    row.title = "New"
    row.updated_at = datetime(2030, 1, 1)  # force updated_at > synced_at
    await db_session.commit()

    await svc._push()
    patches = [c for c in api.calls if c["method"] == "PATCH"]
    assert len(patches) == 1
    assert patches[0]["if_match"] == "etag-old"  # optimistic concurrency
    assert "g3" in patches[0]["url"]
    # etag refreshed + re-synced.
    await db_session.refresh(row)
    assert row.etag == "etag-new"


@pytest.mark.asyncio
async def test_push_skips_unchanged_after_pull(db_session):
    """A freshly pulled row (synced_at==updated_at) must not be pushed."""
    api = FakeAPI()
    acct = GoogleSyncAccount(credentials_encrypted="x", calendar_enabled=True, calendar_sync_token="t")
    svc = CalendarSyncService(db_session, acct, api)
    await svc._apply_event(_all_day_event("g4", "Stable"), "primary")
    await db_session.commit()
    await svc._push()
    assert not [c for c in api.calls if c["method"] == "PATCH"]


@pytest.mark.asyncio
async def test_push_deletion_clears_external_id(db_session):
    api = FakeAPI()
    acct = GoogleSyncAccount(credentials_encrypted="x", calendar_enabled=True, calendar_sync_token="t")
    svc = CalendarSyncService(db_session, acct, api)
    await svc._apply_event(_all_day_event("g5", "Bye"), "primary")
    await db_session.commit()
    row = await db_session.scalar(
        select(ScheduleEvent).where(ScheduleEvent.external_id == "g5")
    )
    row.is_deleted = True
    row.deleted_at = datetime.now()
    await db_session.commit()

    await svc._push()
    deletes = [c for c in api.calls if c["method"] == "DELETE"]
    assert len(deletes) == 1
    await db_session.refresh(row)
    assert row.external_id is None  # won't be re-pulled


def test_rrule_round_trip():
    assert _rrule_from_google(["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]) == "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    assert _rrule_to_google("FREQ=DAILY") == ["RRULE:FREQ=DAILY"]
    assert _rrule_from_google(None) is None
    assert _rrule_to_google(None) is None


def test_google_to_local_all_day_and_timed():
    dt, all_day = _google_to_local({"date": "2026-07-20"})
    assert all_day is True and dt == datetime(2026, 7, 20, 0, 0)
    assert _google_to_local(None) == (None, False)
    # Timed value converts to a naive-local datetime (TZ-dependent, so just shape-check).
    dt2, all_day2 = _google_to_local({"dateTime": "2026-07-20T10:00:00+00:00"})
    assert all_day2 is False and dt2 is not None and dt2.tzinfo is None


@pytest.mark.asyncio
async def test_orchestrator_isolates_failures(db_session, monkeypatch):
    """A failing Calendar sync still lets Tasks run; both are reported."""
    from app.services import google_sync_service as gss

    acct = GoogleSyncAccount(
        credentials_encrypted=encrypt('{"a":1}'),
        calendar_enabled=True,
        tasks_enabled=True,
    )
    db_session.add(acct)
    await db_session.commit()

    # CalendarSyncService.sync blows up; TasksSyncService.sync returns ok.
    async def boom(self, *a, **k):
        raise RuntimeError("cal down")

    monkeypatch.setattr(gss.CalendarSyncService, "sync", boom)
    monkeypatch.setattr(gss.TasksSyncService, "sync", AsyncMock(return_value={"pulled": {"lists": 0}}))
    # Bypass real OAuth client construction.
    monkeypatch.setattr(gss, "GoogleAPIClient", lambda *a, **k: FakeAPI())

    result = await gss.GoogleSyncService(db_session).sync_all()
    assert "cal down" in result["calendar"]["error"]
    assert result["tasks"] == {"pulled": {"lists": 0}}
    await db_session.refresh(acct)
    assert acct.last_sync_error and "cal down" in acct.last_sync_error
    assert acct.last_synced_at is not None


@pytest.mark.asyncio
async def test_tasks_apply_creates_task(db_session):
    api = FakeAPI()
    acct = GoogleSyncAccount(credentials_encrypted="x", tasks_enabled=True)
    svc = TasksSyncService(db_session, acct, api)
    from app.models.task import Task, TaskList

    tl = TaskList(name="My List", source="google", external_id="list-1")
    db_session.add(tl)
    await db_session.commit()
    await db_session.refresh(tl)

    gtask = {
        "id": "t1",
        "title": "Buy milk",
        "notes": "oat",
        "status": "completed",
        "completed": "2026-07-19T07:00:00Z",
        "due": "2026-07-20T23:59:00Z",
    }
    await svc._apply_task(gtask, "list-1", tl)
    await db_session.commit()
    row = await db_session.scalar(select(Task).where(Task.external_id == "t1"))
    assert row is not None
    assert row.source == "google"
    assert row.title == "Buy milk"
    assert row.is_completed is True
    assert row.completed_at is not None
    assert row.list_id == tl.id
