"""Composer context sidebar: local photos by date + read-only ICS calendar.

Local-only by design: both endpoints take the filesystem path **per request**,
so the backend persists nothing (no settings rows, no DB writes) and the
feature-off state has nothing to gate server-side — the client simply never
calls. Opt-in lives in the frontend; see ``ContextDrawerPanel.vue``.

Sandboxing reuses ``media_service.validate_import_path`` wholesale (under
home/temp, no hidden components, sensitive locations denied) — the same
contract as drag-drop media import, not a re-implementation.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.ics_service import parse_ics
from app.services.media_service import validate_import_path

router = APIRouter(prefix="/api/v1/context", tags=["context"])

# Scan cap for the photo directory: os.scandir over 2000 dirents is
# milliseconds; an unbounded walk of a huge library is not. Not recursive —
# top-level camera-roll folders are the target.
_MAX_SCAN = 2000
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}


class PhotoQuery(BaseModel):
    path: str
    date: str | None = Field(default=None, description="YYYY-MM-DD — keep only that day")
    limit: int = Field(default=200, ge=1, le=1000)


class PhotoItem(BaseModel):
    path: str
    filename: str
    size: int
    taken_date: str  # file mtime date (EXIF DateTimeOriginal is a v2 item)
    media_type: str = "image"


class PhotoListing(BaseModel):
    items: list[PhotoItem]
    scanned: int
    truncated: bool


class CalendarQuery(BaseModel):
    path: str
    start_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive")
    limit: int = Field(default=200, ge=1, le=1000)


class CalendarItem(BaseModel):
    uid: str | None
    summary: str
    start: str
    end: str | None
    all_day: bool
    location: str | None
    description: str | None


class CalendarListing(BaseModel):
    items: list[CalendarItem]
    source: str
    warnings: list[str]


def _scan_photo_dir(path: str, day: str | None, limit: int) -> PhotoListing:
    """Synchronous directory scan — caller offloads via ``asyncio.to_thread``."""
    items: list[PhotoItem] = []
    scanned = 0
    truncated = False
    with os.scandir(path) as entries:
        for entry in entries:
            scanned += 1
            if scanned > _MAX_SCAN:
                truncated = True
                break
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in _PHOTO_EXTENSIONS:
                continue
            stat = entry.stat()
            taken = date_type.fromtimestamp(stat.st_mtime).isoformat()
            if day is not None and taken != day:
                continue
            items.append(
                PhotoItem(
                    path=entry.path,
                    filename=entry.name,
                    size=stat.st_size,
                    taken_date=taken,
                )
            )
    items.sort(key=lambda item: item.taken_date, reverse=True)
    truncated = truncated or len(items) > limit
    return PhotoListing(items=items[:limit], scanned=scanned, truncated=truncated)


@router.post("/photos", response_model=PhotoListing)
async def list_local_photos(query: PhotoQuery) -> Any:
    """List image files by date from a user-chosen directory (read-only).

    Nothing is copied or attached here — attaching goes through the normal
    ``POST /api/v1/media/from-path`` pipeline, which re-validates the path.
    """
    directory = validate_import_path(query.path)
    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    return await asyncio.to_thread(_scan_photo_dir, str(directory), query.date, query.limit)


@router.post("/calendar", response_model=CalendarListing)
async def list_local_calendar(query: CalendarQuery) -> Any:
    """Read events from a user-chosen .ics file (read-only, never persisted)."""
    ics_path = validate_import_path(query.path)
    if not ics_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    try:
        text = ics_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise HTTPException(status_code=400, detail="Could not read calendar file") from None

    parsed = parse_ics(text)
    items = [
        CalendarItem(
            uid=e.get("uid"),
            summary=e.get("summary") or "(untitled event)",
            start=e["start"],
            end=e.get("end"),
            all_day=e.get("all_day", False),
            location=e.get("location"),
            description=e.get("description"),
        )
        for e in parsed["events"]
    ]

    def _overlaps(item: CalendarItem) -> bool:
        start_day = item.start[:10]
        end_day = (item.end or item.start)[:10]
        if query.start_date and end_day < query.start_date:
            return False
        if query.end_date and start_day > query.end_date:
            return False
        return True

    if query.start_date or query.end_date:
        items = [i for i in items if _overlaps(i)]
    items = items[: query.limit]
    return CalendarListing(
        items=items,
        source=str(ics_path),
        warnings=list(parsed.get("warnings", [])),
    )
