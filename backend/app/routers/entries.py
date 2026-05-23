"""Journal entry route handlers."""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entry import Entry
from app.models.tag import EntryTag
from app.schemas.entry import EntryCreate, EntryListResponse, EntryResponse, EntryUpdate
from app.schemas.geotagging import GeotagResponse, GeotagUpdate, NearbyEntry, NearbyResponse
from app.schemas.tag import TagBrief
from app.services.entry_service import EntryService

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])


def _to_response(entry: Entry) -> EntryResponse:
    """Convert an Entry ORM object to EntryResponse schema."""
    return EntryResponse(
        id=entry.id,
        entry_date=entry.entry_date,
        title=entry.title,
        body=entry.body,
        mood=entry.mood,
        is_deleted=entry.is_deleted,
        is_encrypted=entry.is_encrypted,
        tags=[TagBrief(id=a.tag.id, name=a.tag.name) for a in entry.tag_associations if a.tag],
        media_count=len(entry.media),
        has_recording=len(entry.recordings) > 0,
        latitude=entry.latitude,
        longitude=entry.longitude,
        location_name=entry.location_name,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.post("", response_model=EntryResponse, status_code=201)
async def create_entry(data: EntryCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a new journal entry."""
    svc = EntryService(db)
    return _to_response(await svc.create(data))


@router.get("", response_model=EntryListResponse)
async def list_entries(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    tag_ids: str | None = Query(None),
    mood: str | None = None,
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List entries with optional filters and pagination."""
    svc = EntryService(db)
    parsed_tag_ids = [int(t) for t in tag_ids.split(",")] if tag_ids else None
    entries, total = await svc.list_entries(offset, limit, parsed_tag_ids, mood, year, month)
    return EntryListResponse(items=[_to_response(e) for e in entries], total=total, offset=offset, limit=limit)


@router.get("/calendar/{year}/{month}", response_model=list[EntryResponse])
async def calendar_view(year: int, month: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Return entries for a specific month."""
    svc = EntryService(db)
    return [_to_response(e) for e in await svc.get_calendar_month(year, month)]


@router.get("/search", response_model=EntryListResponse)
async def search_entries(
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Full-text search on entry bodies."""
    svc = EntryService(db)
    entries, total = await svc.search(q, offset, limit)
    return EntryListResponse(items=[_to_response(e) for e in entries], total=total, offset=offset, limit=limit)


@router.get("/export/markdown")
async def export_markdown(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries as Diarium-compatible markdown files in a .zip.

    Each entry becomes one .md file with YAML frontmatter (date, mood, tags).
    Media files are included in the zip alongside their entries.
    """
    from app.core.config import settings

    q = select(Entry).where(Entry.is_deleted == False).options(  # noqa: E712
        selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
        selectinload(Entry.media),
    ).order_by(Entry.entry_date)

    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)

    result = await db.execute(q)
    entries = list(result.scalars().all())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            tags = [a.tag.name for a in entry.tag_associations if a.tag]
            # YAML frontmatter (Diarium-compatible)
            frontmatter = "---\n"
            frontmatter += f"date: {entry.entry_date}\n"
            if entry.title:
                frontmatter += f"title: {entry.title}\n"
            if entry.mood:
                frontmatter += f"mood: {entry.mood}\n"
            if tags:
                frontmatter += "tags:\n"
                for t in tags:
                    frontmatter += f"  - {t}\n"
            frontmatter += "---\n\n"

            filename = f"entries/{entry.entry_date}.md"
            zf.writestr(filename, frontmatter + entry.body)

            # Include media files
            for media in entry.media:
                media_path = Path(settings.MEDIA_DIR) / media.storage_path
                if media_path.exists():
                    zf.write(str(media_path), f"media/{media.storage_path}")

        # Add manifest
        manifest = {
            "format": "diarium-markdown",
            "version": "1.0",
            "exported_entries": len(entries),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=diarium-export.zip"},
    )


# ── Geotagging endpoints ───────────────────────────────────────────────────────

@router.put("/{entry_id}/geotag", response_model=GeotagResponse)
async def set_geotag(
    entry_id: int, data: GeotagUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Set or update the geolocation of an entry."""
    svc = EntryService(db)
    entry = await svc.get(entry_id)
    entry.latitude = data.latitude
    entry.longitude = data.longitude
    entry.location_name = data.location_name
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}/geotag", status_code=204)
async def remove_geotag(entry_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Remove geolocation from an entry."""
    svc = EntryService(db)
    entry = await svc.get(entry_id)
    entry.latitude = None
    entry.longitude = None
    entry.location_name = None
    await db.commit()


@router.get("/map", response_model=list[GeotagResponse])
async def map_view(db: AsyncSession = Depends(get_db)) -> Any:
    """Return all geotagged entries for map display."""
    result = await db.execute(
        select(Entry).where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.latitude.is_not(None),
            Entry.longitude.is_not(None),
        )
    )
    return list(result.scalars().all())


@router.get("/nearby", response_model=NearbyResponse)
async def nearby_entries(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=10, ge=0.1, le=1000),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Find entries near a given lat/lon within radius_km using Haversine."""
    # Rough bounding box for pre-filtering
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

    result = await db.execute(
        select(Entry).where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.latitude.is_not(None),
            Entry.longitude.is_not(None),
            Entry.latitude.between(lat - lat_delta, lat + lat_delta),
            Entry.longitude.between(lon - lon_delta, lon + lon_delta),
        )
    )
    candidates = list(result.scalars().all())

    # Exact Haversine filtering
    nearby = []
    for e in candidates:
        if e.latitude is None or e.longitude is None:
            continue
        dlat = math.radians(e.latitude - lat)
        dlon = math.radians(e.longitude - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(e.latitude)) * math.sin(dlon / 2) ** 2
        dist = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        if dist <= radius_km:
            nearby.append(NearbyEntry(
                id=e.id,
                entry_date=str(e.entry_date),
                title=e.title,
                latitude=e.latitude,
                longitude=e.longitude,
                location_name=e.location_name,
                distance_km=round(dist, 2),
            ))

    nearby.sort(key=lambda x: x.distance_km)
    return NearbyResponse(items=nearby[:limit], total=len(nearby))


@router.post("/deduplicate", response_model=dict)
async def deduplicate_entries(db: AsyncSession = Depends(get_db)) -> Any:
    """Find and soft-delete duplicate entries.

    Entries are considered duplicates if they share the same entry_date and
    normalized body (whitespace-collapsed, case-insensitive). For each group,
    the oldest entry is kept and the rest are soft-deleted.
    """
    from sqlalchemy import text

    # Find duplicate groups: same date + same normalized body, more than 1 entry
    result = await db.execute(text("""
        SELECT entry_date,
               LOWER(REPLACE(REPLACE(body, CHAR(10), ' '), CHAR(13), '')) AS norm_body,
               GROUP_CONCAT(id) AS ids
        FROM entries
        WHERE is_deleted = 0
        GROUP BY entry_date, norm_body
        HAVING COUNT(*) > 1
    """))
    rows = result.fetchall()

    if not rows:
        return {"groups_found": 0, "duplicates_removed": 0}

    total_removed = 0
    for row in rows:
        id_list = [int(x) for x in row[2].split(",")]
        # Keep the first (oldest) id, delete the rest
        ids_to_delete = id_list[1:]
        for eid in ids_to_delete:
            from datetime import datetime
            await db.execute(
                text("UPDATE entries SET is_deleted = 1, deleted_at = :now WHERE id = :id"),
                {"now": datetime.now(), "id": eid},
            )
            total_removed += 1

    await db.commit()
    return {"groups_found": len(rows), "duplicates_removed": total_removed}


@router.get("/{entry_id}", response_model=EntryResponse)
async def get_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a single entry by ID."""
    svc = EntryService(db)
    return _to_response(await svc.get(entry_id))


@router.patch("/{entry_id}", response_model=EntryResponse)
async def update_entry(entry_id: int, data: EntryUpdate, db: AsyncSession = Depends(get_db)) -> Any:
    """Update an existing entry."""
    svc = EntryService(db)
    return _to_response(await svc.update(entry_id, data))


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete an entry and cascade media."""
    svc = EntryService(db)
    await svc.soft_delete(entry_id)


@router.post("/reset", response_model=dict)
async def reset_database(db: AsyncSession = Depends(get_db)) -> Any:
    """Delete all entries, tags, and associated data. Irreversible."""
    from sqlalchemy import text

    tables = [
        "entry_tags", "entry_revisions", "media", "voice_recordings",
        "video_notes", "ocr_results", "entries", "tags",
        "sync_queue",
    ]
    for table in tables:
        await db.execute(text(f"DELETE FROM {table}"))
    try:
        await db.execute(text("DELETE FROM sqlite_sequence"))
    except Exception:
        pass
    await db.commit()
    return {"status": "ok", "message": "Database cleared."}


@router.post("/import", response_model=dict)
async def import_entries(
    payload: list[dict[str, Any]],
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Import entries from a JSON array. Each entry needs at least entry_date and body."""
    svc = EntryService(db)
    imported = 0
    skipped = 0
    for item in payload:
        entry_date = item.get("entry_date")
        body = item.get("body")
        if not entry_date or not body:
            skipped += 1
            continue
        title = item.get("title")
        mood = item.get("mood")
        data = EntryCreate(
            entry_date=entry_date,
            title=title,
            body=body,
            mood=mood,
            tag_ids=[],
        )
        try:
            await svc.create(data)
            imported += 1
        except Exception:
            pass
            # Skip duplicates (same date) or other errors
            skipped += 1
    return {"imported": imported, "skipped": skipped}


@router.post("/import/file", response_model=dict)
async def import_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Import entries from an uploaded file (ZIP, JSON, or Diarium .diary).

    Supports:
    - Diarium .diary SQLite database
    - Diarium JSON export (array of entries with date/html/heading/tags/rating)
    - Markdown ZIP (entries/*.md with YAML frontmatter: date, mood, tags)
    """
    import shutil
    from datetime import date as date_type

    from sqlalchemy import select

    from app.models.tag import Tag

    svc = EntryService(db)
    filename = file.filename or ""

    entries_data: list[dict[str, Any]] = []

    if filename.endswith(".diary"):
        # Diarium SQLite database — stream to temp file
        import sqlite3 as sqlite3_mod
        import tempfile
        from pathlib import Path as PathLib
        from datetime import datetime as dt_mod
        import datetime as dt_pkg

        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        shutil.copyfileobj(file.file, tmp)
        tmp.close()
        try:
            conn = sqlite3_mod.connect(tmp.name)
            conn.row_factory = sqlite3_mod.Row
            rows = conn.execute("SELECT e.DiaryEntryId, e.Heading, e.Text, e.Rating, e.Latitude, e.Longitude FROM Entries e ORDER BY e.DiaryEntryId").fetchall()

            tag_rows = conn.execute("SELECT et.DiaryEntryId, t.Value FROM EntryTags et JOIN Tags t ON et.DiaryTagId = t.DiaryTagId").fetchall()
            entry_tags_map: dict[int, list[str]] = {}
            for tr in tag_rows:
                entry_tags_map.setdefault(tr["DiaryEntryId"], []).append(tr["Value"])

            for row in rows:
                ticks = row["DiaryEntryId"]
                try:
                    us = (ticks - 621355968000000000) / 10
                    entry_dt = dt_mod.fromtimestamp(us / 1_000_000, tz=dt_pkg.timezone.utc)
                    entry_date_str = entry_dt.strftime("%Y-%m-%d")
                except Exception:
                    continue

                heading = re.sub(r"<[^>]+>", "", row["Heading"] or "").strip() or None
                body_text = row["Text"] or ""
                if body_text:
                    body_text = re.sub(r"<br\s*/?>", "\n", body_text)
                    body_text = re.sub(r"</?p>", "\n", body_text)
                    body_text = re.sub(r"<[^>]+>", "", body_text).strip()

                if not body_text:
                    continue

                if heading == "Today's Summary":
                    heading = None

                mood_val = None
                rating = row["Rating"]
                if rating and isinstance(rating, (int, float)) and 1 <= int(rating) <= 5:
                    mood_val = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}.get(int(rating))

                entries_data.append({
                    "entry_date": entry_date_str,
                    "title": heading,
                    "body": body_text,
                    "mood": mood_val,
                    "tags": entry_tags_map.get(row["DiaryEntryId"], []),
                    "latitude": row["Latitude"] if row["Latitude"] else None,
                    "longitude": row["Longitude"] if row["Longitude"] else None,
                })
            conn.close()
        finally:
            PathLib(tmp.name).unlink(missing_ok=True)

    else:
        # Small files — read into memory
        content = await file.read()

        if filename.endswith(".zip"):
            import zipfile as zf

            buf = io.BytesIO(content)
            with zf.ZipFile(buf, "r") as z:
                names = z.namelist()

                json_files = [n for n in names if n.endswith(".json") and n != "manifest.json"]
                if json_files:
                    for jf in json_files:
                        try:
                            entry = json.loads(z.read(jf))
                            entries_data.append(_parse_diarium_json_entry(entry))
                        except Exception:
                            pass

                if not json_files:
                    for n in names:
                        if n == "entries.json" or n == "diarium.json":
                            try:
                                data = json.loads(z.read(n))
                                if isinstance(data, list):
                                    for entry in data:
                                        entries_data.append(_parse_diarium_json_entry(entry))
                            except Exception:
                                pass

                md_files = sorted([n for n in names if n.endswith(".md")])
                for mf in md_files:
                    raw = z.read(mf).decode("utf-8")
                    entry = _parse_markdown_entry(raw)
                    if entry:
                        entries_data.append(entry)

        elif filename.endswith(".json"):
            data = json.loads(content)
            items = data if isinstance(data, list) else data.get("entries", [])
            for item in items:
                parsed = _parse_diarium_json_entry(item)
                if not parsed.get("body") and not parsed.get("entry_date"):
                    parsed = {
                        "entry_date": item.get("entry_date") or item.get("date", "")[:10],
                        "title": item.get("title") or item.get("heading"),
                        "body": item.get("body", ""),
                        "mood": item.get("mood"),
                        "tags": item.get("tags", []),
                    }
                entries_data.append(parsed)

    # Import all parsed entries
    imported = 0
    skipped = 0
    for entry in entries_data:
        if not entry.get("entry_date") or not entry.get("body"):
            skipped += 1
            continue
        try:
            ed = entry["entry_date"]
            if isinstance(ed, str):
                ed = date_type.fromisoformat(ed[:10])

            # Resolve tag names to IDs (create tags if needed)
            tag_ids: list[int] = []
            for tag_name in entry.get("tags", []):
                if not tag_name:
                    continue
                result = await db.execute(select(Tag).where(Tag.name == tag_name))
                tag = result.scalar_one_or_none()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    await db.flush()
                    await db.refresh(tag)
                tag_ids.append(tag.id)

            data = EntryCreate(
                entry_date=ed,
                title=entry.get("title"),
                body=entry["body"],
                mood=entry.get("mood"),
                tag_ids=tag_ids,
            )
            await svc.create(data)
            imported += 1
        except Exception:
            pass
            skipped += 1

    return {"imported": imported, "skipped": skipped}


def _parse_diarium_json_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Parse a single Diarium JSON entry into our import format."""
    import re

    # Diarium date format: "2026-01-15T00:00:00.0000000+00:00" or similar
    raw_date = str(item.get("date", ""))[:10]

    # Body: prefer "text" then "html" then "content"
    body = item.get("text", "") or item.get("content", "")
    if not body and item.get("html"):
        # Strip basic HTML tags for markdown body
        body = re.sub(r"<br\s*/?>", "\n", item["html"])
        body = re.sub(r"</?p>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body).strip()

    # Title from heading (may be HTML)
    title = item.get("heading", "")
    if title:
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title:
            title = None

    # Mood from rating (1-5 scale)
    mood = None
    rating = item.get("rating")
    if rating and isinstance(rating, (int, float)):
        moods = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}
        mood = moods.get(int(rating))

    tags = item.get("tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return {
        "entry_date": raw_date,
        "title": title,
        "body": body,
        "mood": mood,
        "tags": tags,
    }


def _parse_markdown_entry(raw: str) -> dict[str, Any] | None:
    """Parse a markdown file with YAML frontmatter into an import dict."""

    if not raw.startswith("---"):
        # No frontmatter — try to extract date from filename later
        body = raw.strip()
        if not body:
            return None
        return {"entry_date": "", "title": None, "body": body, "mood": None, "tags": []}

    # Extract frontmatter
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()
    body = parts[2].strip()
    if not body:
        return None

    entry_date = ""
    title = None
    mood = None
    tags: list[str] = []

    for line in frontmatter.split("\n"):
        line = line.strip()
        if line.startswith("date:"):
            entry_date = line.split(":", 1)[1].strip()[:10]
        elif line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("mood:"):
            mood = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("  - "):
            tags.append(line[4:].strip())

    return {
        "entry_date": entry_date,
        "title": title,
        "body": body,
        "mood": mood,
        "tags": tags,
    }
