"""Two-way Google Calendar sync.

Pull: list the account's writable calendars, then each calendar's events — a
full listing on the first run, and incremental thereafter via Google's
``syncToken`` (which also reports cancellations). Events are upserted into
``ScheduleEvent`` keyed by ``external_id`` (``source='google'``); cancellations
soft-delete the local row.

Push: local edits to ``source='google'`` events (``updated_at > synced_at``) are
PATCHed back to their calendar, etag-guarded (``If-Match``). A ``412`` means the
remote changed since our etag — we re-fetch and let the remote copy win (safe;
no clobbering of either side beyond the conflict). Locally soft-deleted
``source='google'`` events are DELETEd on Google, then their ``external_id`` is
cleared so they aren't re-pulled.

``source='manual'`` events are never pushed (local-only stays local).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule_event import ScheduleEvent
from app.services.google_oauth import GoogleAPIClient
from app.services.google_sync_utils import local_tz, mark_synced

logger = logging.getLogger(__name__)

_CAL_BASE = "https://www.googleapis.com/calendar/v3"
# Only sync calendars we can write to (skips subscribed holiday/birthday lists).
_WRITABLE_ROLES = {"owner", "writer"}


def _google_to_local(value: dict[str, str] | None) -> tuple[datetime | None, bool]:
    """Convert a Google event start/end block to (naive-local dt, all_day)."""
    if not value:
        return None, False
    if "date" in value:  # all-day: "YYYY-MM-DD"
        try:
            return datetime.fromisoformat(value["date"]), True
        except ValueError:
            return None, True
    if "dateTime" in value:
        try:
            dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
        except ValueError:
            return None, False
        return dt.astimezone().replace(tzinfo=None), False
    return None, False


def _local_to_google_dt(dt: datetime, all_day: bool) -> dict[str, str]:
    """Convert a naive-local dt to a Google start/end block."""
    if all_day:
        return {"date": dt.date().isoformat()}
    return {"dateTime": dt.replace(tzinfo=local_tz()).isoformat()}


def _rrule_from_google(recurrence: list[str] | None) -> str | None:
    """Extract the RRULE spec (without the ``RRULE:`` prefix) from a Google event."""
    if not recurrence:
        return None
    for line in recurrence:
        if line.startswith("RRULE:"):
            return line.removeprefix("RRULE:")
    return None


def _rrule_to_google(rrule: str | None) -> list[str] | None:
    return [f"RRULE:{rrule}"] if rrule else None


class CalendarSyncService:
    """Two-way sync between a Google account's calendars and ``ScheduleEvent``."""

    def __init__(self, db: AsyncSession, account: Any, api: GoogleAPIClient) -> None:
        self.db = db
        self.account = account
        self.api = api

    async def sync(self) -> dict[str, Any]:
        if not self.account.calendar_enabled:
            return {"skipped": "calendar disabled"}
        try:
            pulled = await self._pull()
            pushed = await self._push()
            await self.db.commit()
            return {"pulled": pulled, "pushed": pushed}
        except Exception:
            await self.db.rollback()
            raise

    # ── Pull (Google → local) ────────────────────────────────────────────

    async def _pull(self) -> dict[str, int]:
        stats = {"calendars": 0, "events": 0}
        try:
            resp = await self.api.request("GET", f"{_CAL_BASE}/users/me/calendarList")
            calendars = resp.json().get("items", [])
        except Exception:
            logger.warning("Google calendarList failed", exc_info=True)
            return stats
        for cal in calendars:
            if cal.get("accessRole") not in _WRITABLE_ROLES:
                continue
            cal_id = cal.get("id")
            if cal_id:
                stats["calendars"] += 1
                await self._sync_calendar(cal_id, stats)
        return stats

    async def _sync_calendar(self, cal_id: str, stats: dict[str, int]) -> None:
        url = f"{_CAL_BASE}/calendars/{cal_id}/events"
        params: dict[str, Any] = {}
        if self.account.calendar_sync_token:
            params["syncToken"] = self.account.calendar_sync_token
        else:
            # Keep recurring masters intact (don't expand into single instances).
            params["singleEvents"] = "false"
        full_retry = False
        while True:
            try:
                resp = await self.api.request("GET", url, params=params)
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                # Sync tokens expire (410 Gone) → drop it and do one full re-sync.
                if exc.response.status_code == 410 and not full_retry:
                    logger.info("Calendar syncToken expired (410) — full re-sync of %s", cal_id)
                    self.account.calendar_sync_token = None
                    full_retry = True
                    params = {"singleEvents": "false"}
                    continue
                raise
            for ev in data.get("items", []):
                await self._apply_event(ev, cal_id)
                stats["events"] += 1
            if data.get("nextSyncToken"):
                self.account.calendar_sync_token = data["nextSyncToken"]
            if data.get("nextPageToken"):
                params = {"pageToken": data["nextPageToken"]}
                continue
            break

    async def _apply_event(self, ev: dict[str, Any], cal_id: str) -> None:
        ext_id = ev.get("id")
        if not ext_id:
            return
        existing = await self.db.scalar(
            select(ScheduleEvent).where(
                ScheduleEvent.source == "google",
                ScheduleEvent.external_id == ext_id,
            )
        )
        # Cancellation → soft-delete locally (if present and not already).
        if ev.get("status") == "cancelled":
            if existing is not None and not existing.is_deleted:
                existing.is_deleted = True
                existing.deleted_at = datetime.now()
                await mark_synced(self.db,existing)
            return

        start, all_day = _google_to_local(ev.get("start"))
        end, _end_all_day = _google_to_local(ev.get("end"))
        if start is None or end is None:
            return  # incomplete (e.g. a hangout without times)

        fields = {
            "title": ev.get("summary") or "(untitled)",
            "description": ev.get("description"),
            "location": ev.get("location"),
            "start_at": start,
            "end_at": end,
            "all_day": all_day,
            "rrule": _rrule_from_google(ev.get("recurrence")),
            "external_calendar_id": cal_id,
            "etag": ev.get("etag"),
            "is_deleted": False,
            "deleted_at": None,
        }
        if existing is None:
            existing = ScheduleEvent(source="google", external_id=ext_id, **fields)
            self.db.add(existing)
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
        await mark_synced(self.db,existing)

    # ── Push (local → Google) ────────────────────────────────────────────

    async def _push(self) -> dict[str, int]:
        stats = {"updated": 0, "deleted": 0, "conflicts": 0}

        # 1. Deletions: source='google', soft-deleted, external_id still set.
        for ev in (
            await self.db.scalars(
                select(ScheduleEvent).where(
                    ScheduleEvent.source == "google",
                    ScheduleEvent.is_deleted == True,  # noqa: E712
                    ScheduleEvent.external_id.isnot(None),
                )
            )
        ).all():
            cal_id = ev.external_calendar_id or "primary"
            try:
                await self.api.request(
                    "DELETE", f"{_CAL_BASE}/calendars/{cal_id}/events/{ev.external_id}"
                )
                stats["deleted"] += 1
            except httpx.HTTPStatusError as exc:
                # 404/410 = already gone on Google — treat as deleted.
                if exc.response.status_code in (404, 410):
                    stats["deleted"] += 1
                else:
                    logger.warning("Failed to delete Google event %s", ev.external_id, exc_info=True)
            ev.external_id = None
            ev.external_calendar_id = None

        # 2. Edits: source='google', not deleted, locally changed since last sync.
        for ev in (
            await self.db.scalars(
                select(ScheduleEvent).where(
                    ScheduleEvent.source == "google",
                    ScheduleEvent.is_deleted == False,  # noqa: E712
                    ScheduleEvent.external_id.isnot(None),
                    ScheduleEvent.synced_at.isnot(None),
                    ScheduleEvent.updated_at > ScheduleEvent.synced_at,
                )
            )
        ).all():
            cal_id = ev.external_calendar_id or "primary"
            body = {
                "summary": ev.title,
                "description": ev.description,
                "location": ev.location,
                "start": _local_to_google_dt(ev.start_at, ev.all_day),
                "end": _local_to_google_dt(ev.end_at, ev.all_day),
                "recurrence": _rrule_to_google(ev.rrule),
            }
            try:
                resp = await self.api.request(
                    "PATCH",
                    f"{_CAL_BASE}/calendars/{cal_id}/events/{ev.external_id}",
                    json_body=body,
                    if_match=ev.etag,
                )
                ev.etag = resp.json().get("etag")
                await mark_synced(self.db,ev)
                stats["updated"] += 1
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 412:
                    # Remote changed since our etag → re-fetch, remote wins.
                    stats["conflicts"] += 1
                    logger.info("Conflict pushing event %s — re-fetching", ev.external_id)
                    await self._refetch_and_merge(ev, cal_id)
                else:
                    logger.warning("Failed to push Google event %s", ev.external_id, exc_info=True)
        return stats

    async def _refetch_and_merge(self, ev: ScheduleEvent, cal_id: str) -> None:
        """On a 412 conflict, overwrite the local row with the remote version."""
        try:
            resp = await self.api.request(
                "GET", f"{_CAL_BASE}/calendars/{cal_id}/events/{ev.external_id}"
            )
            remote = resp.json()
        except Exception:
            logger.warning("Conflict re-fetch failed for %s", ev.external_id, exc_info=True)
            return
        start, all_day = _google_to_local(remote.get("start"))
        end, _ = _google_to_local(remote.get("end"))
        if start and end:
            ev.title = remote.get("summary") or ev.title
            ev.description = remote.get("description")
            ev.location = remote.get("location")
            ev.start_at, ev.end_at, ev.all_day = start, end, all_day
            ev.rrule = _rrule_from_google(remote.get("recurrence"))
            ev.etag = remote.get("etag")
            await mark_synced(self.db,ev)
