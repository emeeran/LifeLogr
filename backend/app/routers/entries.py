"""Journal entry route handlers."""

from __future__ import annotations

import io
import json
import logging
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
from app.schemas.entry import (
    CalendarEntryResponse,
    EntryCreate,
    EntryListItem,
    EntryListResponse,
    EntryResponse,
    EntryUpdate,
)
from app.schemas.tag import TagBrief
from app.services.entry_service import EntryService
from app.services.export_service import build_diarium_database
from app.services.importers import (
    parse_csv,
    parse_dayone_zip,
    parse_diarium_json_entry,
    parse_diarium_sqlite,
    parse_markdown_entry,
)

logger = logging.getLogger(__name__)

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
        template_id=entry.template_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _to_list_item(entry: Entry, snippet: str) -> EntryListItem:
    """Convert an Entry (loaded WITHOUT its body) to a lightweight list item.

    ``snippet`` is a server-side truncation of the body (empty for encrypted
    entries), so the full body never has to be loaded for list/timeline views.
    """
    return EntryListItem(
        id=entry.id,
        entry_date=entry.entry_date,
        title=entry.title,
        body_snippet=snippet,
        mood=entry.mood,
        is_deleted=entry.is_deleted,
        is_encrypted=entry.is_encrypted,
        tags=[TagBrief(id=a.tag.id, name=a.tag.name) for a in entry.tag_associations if a.tag],
        media_count=len(entry.media),
        has_recording=len(entry.recordings) > 0,
        latitude=entry.latitude,
        longitude=entry.longitude,
        location_name=entry.location_name,
        template_id=entry.template_id,
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
    template_id: int | None = Query(None, description="Only entries created from this template"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List entries with optional filters and pagination."""
    svc = EntryService(db)
    parsed_tag_ids = [int(t) for t in tag_ids.split(",")] if tag_ids else None
    entries, total = await svc.list_entries(
        offset, limit, parsed_tag_ids, mood, year, month, template_id
    )
    snippets = await svc.body_snippets([e.id for e in entries])
    return EntryListResponse(
        items=[_to_list_item(e, snippets.get(e.id, "")) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/calendar/{year}/{month}", response_model=list[CalendarEntryResponse])
async def calendar_view(year: int, month: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Return lightweight entry projections for a calendar month.

    Excludes body/media fields to keep the payload small — the grid only
    needs id, date, title, mood, and tags.
    """
    svc = EntryService(db)
    return await svc.get_calendar_month_light(year, month)


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
    snippets = await svc.body_snippets([e.id for e in entries])
    return EntryListResponse(
        items=[_to_list_item(e, snippets.get(e.id, "")) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
    )


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

    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
            selectinload(Entry.media),
        )
        .order_by(Entry.entry_date)
    )

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


@router.get("/export/diarium")
async def export_diarium(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries in Diarium-compatible JSON format.

    Produces a JSON array where each entry has: date, text, heading, rating, tags.
    This format can be imported directly by Diarium or re-imported here.
    """
    mood_to_rating = {"awful": 1, "bad": 2, "meh": 3, "good": 4, "great": 5}

    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
        )
        .order_by(Entry.entry_date)
    )

    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)

    result = await db.execute(q)
    entries = list(result.scalars().all())

    export_items = []
    for entry in entries:
        tags = [a.tag.name for a in entry.tag_associations if a.tag]
        item: dict[str, Any] = {
            "date": str(entry.entry_date) + "T00:00:00.0000000+00:00",
            "text": entry.body or "",
        }
        if entry.title:
            item["heading"] = entry.title
        if entry.mood and entry.mood in mood_to_rating:
            item["rating"] = mood_to_rating[entry.mood]
        if tags:
            item["tags"] = tags
        export_items.append(item)

    content = json.dumps(export_items, indent=2, ensure_ascii=False)
    buf = io.BytesIO(content.encode("utf-8"))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=diarium-export.json"},
    )


@router.get("/export/json")
async def export_json(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries as a portable LifeLogr JSON document.

    Schema: ``{"app":"lifelogr","version":1,"entries":[{entry_date,title,body,mood,tags}]}``.
    Round-trips through the ``/import/file`` JSON importer.
    """
    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(selectinload(Entry.tag_associations).selectinload(EntryTag.tag))
        .order_by(Entry.entry_date)
    )
    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)
    result = await db.execute(q)
    entries = list(result.scalars().all())

    items: list[dict[str, Any]] = []
    for entry in entries:
        tags = [a.tag.name for a in entry.tag_associations if a.tag]
        item: dict[str, Any] = {
            "entry_date": str(entry.entry_date),
            "title": entry.title,
            "body": entry.body or "",
            "mood": entry.mood,
        }
        if tags:
            item["tags"] = tags
        items.append(item)

    payload = {"app": "lifelogr", "version": 1, "entries": items}
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    buf = io.BytesIO(content.encode("utf-8"))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=lifelogr-export.json"},
    )


# .NET DateTime ticks for 0001-01-01 (the epoch Diarium's DiaryEntryId is based on).
@router.get("/export/diarium-db")
async def export_diarium_db(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries as a Diarium-native .diary SQLite database.

    Produces the real Diarium schema (Entries keyed by .NET DateTime ticks,
    Tags, EntryTags) so the file can be opened/imported directly by the
    Diarium app or re-imported here via the .diary importer.
    """
    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
        )
        .order_by(Entry.entry_date, Entry.id)
    )
    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)

    result = await db.execute(q)
    entries = list(result.scalars().all())

    data = build_diarium_database(entries)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="lifelogr-export.diary"'},
    )


@router.post("/deduplicate", response_model=dict)
async def deduplicate_entries(db: AsyncSession = Depends(get_db)) -> Any:
    """Find and soft-delete duplicate entries.

    Entries are considered duplicates if they share the same entry_date and
    normalized body (whitespace-collapsed, case-insensitive). For each group,
    the oldest entry is kept and the rest are soft-deleted.
    """
    from sqlalchemy import text

    # Find duplicate groups: same date + same normalized body, more than 1 entry
    result = await db.execute(
        text("""
        SELECT entry_date,
               LOWER(REPLACE(REPLACE(body, CHAR(10), ' '), CHAR(13), '')) AS norm_body,
               GROUP_CONCAT(id) AS ids
        FROM entries
        WHERE is_deleted = 0
        GROUP BY entry_date, norm_body
        HAVING COUNT(*) > 1
    """)
    )
    rows = result.fetchall()

    if not rows:
        return {"groups_found": 0, "duplicates_removed": 0}

    from datetime import datetime, timezone

    from sqlalchemy import bindparam

    # Collect every id to soft-delete across all duplicate groups, then issue one
    # bulk UPDATE + a single commit (previously one UPDATE per id).
    ids_to_delete: list[int] = []
    for row in rows:
        id_list = [int(x) for x in row[2].split(",")]
        ids_to_delete.extend(id_list[1:])  # keep the first (oldest), delete the rest

    if ids_to_delete:
        await db.execute(
            text(
                "UPDATE entries SET is_deleted = 1, deleted_at = :now WHERE id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"now": datetime.now(timezone.utc), "ids": ids_to_delete},
        )

    await db.commit()
    return {"groups_found": len(rows), "duplicates_removed": len(ids_to_delete)}


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


@router.post("/{entry_id}/restore", response_model=EntryResponse)
async def restore_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Restore a previously soft-deleted entry (re-indexes it in FTS search)."""
    svc = EntryService(db)
    return _to_response(await svc.restore(entry_id))


@router.post("/reset", response_model=dict)
async def reset_database(db: AsyncSession = Depends(get_db)) -> Any:
    """Delete all entries, tags, and associated data. Irreversible."""
    from sqlalchemy import text

    tables = [
        "entry_tags",
        "media",
        "voice_recordings",
        "video_notes",
        "entries",
        "note_tags",
        "notes",
        "note_folders",
        "note_media",
        "tags",
        "sync_queue",
    ]
    for table in tables:
        await db.execute(text(f"DELETE FROM {table}"))
    try:
        await db.execute(text("DELETE FROM sqlite_sequence"))
    except Exception:
        logger.debug("sqlite_sequence cleanup skipped (may not exist)")
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
        except Exception as e:
            logger.warning("Failed to import entry (date=%s): %s", entry_date, e)
            skipped += 1
    return {"imported": imported, "skipped": skipped}


@router.post("/import/file", response_model=dict)
async def import_file(
    file: UploadFile = File(...),
    skip_duplicates: bool = Query(
        True, description="Skip entries already present (same date + body)"
    ),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Import entries from an uploaded file (ZIP, JSON, or Diarium .diary).

    Supports:
    - Diarium .diary SQLite database
    - Diarium JSON export (array of entries with date/html/heading/tags/rating)
    - Markdown ZIP (entries/*.md with YAML frontmatter: date, mood, tags)
    """
    import hashlib
    from datetime import date as date_type

    from sqlalchemy import select

    from app.models.tag import Tag

    svc = EntryService(db)
    filename = file.filename or ""

    entries_data: list[dict[str, Any]] = []

    if filename.endswith(".diary"):
        # Diarium .diary SQLite database — parsing lives in the importers service.
        entries_data.extend(parse_diarium_sqlite(await file.read()))

    else:
        # Small files — read into memory
        content = await file.read()

        if filename.endswith(".zip"):
            import zipfile as zf

            buf = io.BytesIO(content)
            # Day One exports carry Journal.json — detect and handle first.
            is_dayone = False
            try:
                with zf.ZipFile(buf, "r") as z:
                    is_dayone = any(n.endswith("Journal.json") for n in z.namelist())
            except zipfile.BadZipFile:
                pass

            if is_dayone:
                entries_data.extend(parse_dayone_zip(content))
            else:
                buf.seek(0)
                with zf.ZipFile(buf, "r") as z:
                    names = z.namelist()

                    json_files = [n for n in names if n.endswith(".json") and n != "manifest.json"]
                    if json_files:
                        for jf in json_files:
                            try:
                                entry = json.loads(z.read(jf))
                                entries_data.append(parse_diarium_json_entry(entry))
                            except Exception:
                                logger.warning("Failed to parse JSON entry from %s", jf)

                    if not json_files:
                        for n in names:
                            if n == "entries.json" or n == "diarium.json":
                                try:
                                    data = json.loads(z.read(n))
                                    if isinstance(data, list):
                                        for entry in data:
                                            entries_data.append(parse_diarium_json_entry(entry))
                                except Exception:
                                    logger.warning("Failed to parse bulk JSON from %s", n)

                    md_files = sorted([n for n in names if n.endswith(".md")])
                    for mf in md_files:
                        raw = z.read(mf).decode("utf-8")
                        entry = parse_markdown_entry(raw)
                        if entry:
                            entries_data.append(entry)

        elif filename.endswith(".csv"):
            entries_data.extend(parse_csv(content.decode("utf-8", errors="replace")))

        elif filename.endswith(".json"):
            data = json.loads(content)
            items = data if isinstance(data, list) else data.get("entries", [])
            for item in items:
                parsed = parse_diarium_json_entry(item)
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
    # Pre-load all existing tags to avoid N+1 lookups
    existing_tags_result = await db.execute(select(Tag))
    tag_cache: dict[str, Tag] = {t.name: t for t in existing_tags_result.scalars().all()}

    # Duplicate detection: (entry_date, sha256(body[:1000])) of existing rows.
    existing_sigs: set[tuple[str, str]] = set()
    if skip_duplicates:
        _rows = await db.execute(select(Entry.entry_date, Entry.body).where(~Entry.is_deleted))
        for _ed, _body in _rows.all():
            existing_sigs.add((str(_ed), hashlib.sha256((_body or "")[:1000].encode()).hexdigest()))

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

            sig = (
                str(ed),
                hashlib.sha256((entry["body"] or "")[:1000].encode()).hexdigest(),
            )
            if skip_duplicates and sig in existing_sigs:
                skipped += 1
                continue

            # Resolve tag names to IDs (create tags if needed)
            tag_ids: list[int] = []
            has_new_tags = False
            for tag_name in entry.get("tags", []):
                if not tag_name:
                    continue
                tag = tag_cache.get(tag_name)
                if not tag:
                    tag = Tag(name=tag_name)
                    tag_cache[tag_name] = tag
                    db.add(tag)
                    has_new_tags = True
            if has_new_tags:
                await db.flush()
            tag_ids = [tag_cache[tn].id for tn in entry.get("tags", []) if tn and tag_cache.get(tn)]

            data = EntryCreate(
                entry_date=ed,
                title=entry.get("title"),
                body=entry["body"],
                mood=entry.get("mood"),
                tag_ids=tag_ids,
            )
            await svc.create(data)
            existing_sigs.add(sig)
            imported += 1
        except Exception as e:
            logger.warning("Failed to import entry (date=%s): %s", entry.get("entry_date"), e)
            skipped += 1

    return {"imported": imported, "skipped": skipped}
