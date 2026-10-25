"""Integration tests for the context sidebar endpoints (local photos + ICS)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.entry import Entry
from app.models.media import Media
from tests.helpers.dayone_zip import PNG_1X1

# Any .ics content with two events on distinct days.
_ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "UID:e1",
        "DTSTART:20260601T090000",
        "DTEND:20260601T100000",
        "SUMMARY:Morning standup",
        "LOCATION:Room 2",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:e2",
        "DTSTART;VALUE=DATE:20260715",
        "SUMMARY:Trip",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
)


def _photo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "photos"
    d.mkdir()
    for name, offset in (("a.png", 0), ("b.jpg", 86_400), ("notes.txt", 0)):
        (d / name).write_bytes(PNG_1X1 if name != "notes.txt" else b"not a photo")
        stamp = time.time() - offset * 2
        os.utime(d / name, (stamp, stamp))
    return d


async def test_photos_listing_groups_by_date(client: AsyncClient, tmp_path) -> None:
    d = _photo_dir(tmp_path)
    r = await client.post("/api/v1/context/photos", json={"path": str(d)})
    assert r.status_code == 200
    body = r.json()
    assert body["scanned"] == 3  # .txt counted as scanned, just not listed
    assert [i["filename"] for i in body["items"]] == ["a.png", "b.jpg"]
    assert body["items"][0]["path"] == str(d / "a.png")
    assert body["truncated"] is False


async def test_photos_listing_date_filter(client: AsyncClient, tmp_path) -> None:
    d = _photo_dir(tmp_path)
    newest = sorted(
        (p for p in d.iterdir() if p.suffix != ".txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[0]
    day = time.strftime("%Y-%m-%d", time.localtime(newest.stat().st_mtime))
    r = await client.post("/api/v1/context/photos", json={"path": str(d), "date": day})
    assert [i["filename"] for i in r.json()["items"]] == [newest.name]


async def test_photos_listing_respects_limit_and_truncated(client: AsyncClient, tmp_path) -> None:
    d = _photo_dir(tmp_path)
    r = await client.post("/api/v1/context/photos", json={"path": str(d), "limit": 1})
    body = r.json()
    assert len(body["items"]) == 1
    assert body["truncated"] is True


async def test_photos_rejects_path_outside_allowed_roots(client: AsyncClient, tmp_path, monkeypatch) -> None:
    from app.services import media_service

    # Deny the temp root the pytest tmp_path lives under.
    monkeypatch.setattr(media_service, "allowed_import_roots", lambda: [Path.home()])
    r = await client.post("/api/v1/context/photos", json={"path": str(tmp_path)})
    assert r.status_code == 400


async def test_photos_rejects_hidden_directory(client: AsyncClient, tmp_path, monkeypatch) -> None:
    # The hidden-component check applies below $HOME — point home at the tmp dir.
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    hidden = tmp_path / ".hiddencam"
    hidden.mkdir()
    r = await client.post("/api/v1/context/photos", json={"path": str(hidden)})
    assert r.status_code == 400


async def test_photos_rejects_missing_path(client: AsyncClient, tmp_path) -> None:
    r = await client.post("/api/v1/context/photos", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 404


async def test_calendar_listing_filters_by_date_range(client: AsyncClient, tmp_path) -> None:
    ics = tmp_path / "cal.ics"
    ics.write_text(_ICS)
    r = await client.post(
        "/api/v1/context/calendar",
        json={"path": str(ics), "start_date": "2026-06-01", "end_date": "2026-06-30"},
    )
    assert r.status_code == 200
    body = r.json()
    assert [i["summary"] for i in body["items"]] == ["Morning standup"]
    assert body["items"][0]["location"] == "Room 2"
    assert body["source"] == str(ics)


async def test_calendar_rejects_directory_path(client: AsyncClient, tmp_path) -> None:
    r = await client.post("/api/v1/context/calendar", json={"path": str(tmp_path)})
    assert r.status_code == 400


async def test_no_db_rows_created_after_listing(client: AsyncClient, db_session, tmp_path) -> None:
    """The acceptance criterion: listing is read-only — nothing persists."""
    d = _photo_dir(tmp_path)
    ics = tmp_path / "cal.ics"
    ics.write_text(_ICS)
    assert (await client.post("/api/v1/context/photos", json={"path": str(d)})).status_code == 200
    assert (
        await client.post("/api/v1/context/calendar", json={"path": str(ics)})
    ).status_code == 200

    media_count = (await db_session.execute(select(func.count()).select_from(Media))).scalar_one()
    entry_count = (await db_session.execute(select(func.count()).select_from(Entry))).scalar_one()
    assert media_count == 0
    assert entry_count == 0
