"""Journal entry route handlers."""

from __future__ import annotations

import io
import json
import logging
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
from app.schemas.entry import (
    CalendarEntryResponse,
    EntryCreate,
    EntryListResponse,
    EntryResponse,
    EntryUpdate,
)
from app.schemas.tag import TagBrief
from app.services.entry_service import EntryService

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
    return EntryListResponse(
        items=[_to_response(e) for e in entries], total=total, offset=offset, limit=limit
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
    return EntryListResponse(
        items=[_to_response(e) for e in entries], total=total, offset=offset, limit=limit
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
_DOTNET_TICKS_EPOCH = 621355968000000000
_TICKS_PER_SECOND = 10_000_000
_MOOD_TO_RATING = {"awful": 1, "bad": 2, "meh": 3, "good": 4, "great": 5}


def _markdown_to_diarium_html(body: str) -> str:
    """Convert a markdown/plain-text body into Diarium-style HTML.

    Diarium stores entry text as HTML (<p>...</p> with <br> line breaks).
    This is the inverse of the HTML-stripping performed by the .diary importer.
    """
    import html as html_mod

    escaped = html_mod.escape(body or "")
    paragraphs = re.split(r"\n\s*\n", escaped)
    rendered = []
    for para in paragraphs:
        if not para.strip():
            continue
        para = para.replace("\n", "<br>")
        rendered.append(f"<p>{para}</p>")
    return "".join(rendered)


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
    import sqlite3
    from datetime import date as date_type
    from datetime import datetime, timezone

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

    conn = sqlite3.connect(":memory:")
    try:
        # Core Diarium tables (text/tags/rating subset — matches what the
        # .diary importer reads back, and what Diarium requires to import).
        conn.executescript(
            """
            CREATE TABLE Entries (
                DiaryEntryId INTEGER PRIMARY KEY,
                Heading     TEXT,
                Text        TEXT,
                Rating      INTEGER DEFAULT 0,
                Latitude    REAL,
                Longitude   REAL
            );
            CREATE TABLE Tags (
                DiaryTagId  INTEGER PRIMARY KEY AUTOINCREMENT,
                Value       TEXT NOT NULL
            );
            CREATE TABLE EntryTags (
                DiaryEntryId INTEGER NOT NULL,
                DiaryTagId   INTEGER NOT NULL,
                PRIMARY KEY (DiaryEntryId, DiaryTagId)
            );
            """
        )

        tag_id_map: dict[str, int] = {}
        used_entry_ids: set[int] = set()

        for entry in entries:
            ed = entry.entry_date
            if isinstance(ed, str):
                ed = date_type.fromisoformat(ed[:10])
            # DiaryEntryId = .NET ticks for the entry date at 00:00:00 UTC.
            midnight = datetime.combine(ed, datetime.min.time(), tzinfo=timezone.utc)
            unix_us = int(midnight.timestamp() * 1_000_000)
            entry_id = _DOTNET_TICKS_EPOCH + unix_us * 10
            # Guarantee uniqueness while staying on the same calendar day
            # (offsets in whole seconds so the importer still resolves the date).
            while entry_id in used_entry_ids:
                entry_id += _TICKS_PER_SECOND
            used_entry_ids.add(entry_id)

            heading = (entry.title or "").strip()
            text_html = _markdown_to_diarium_html(entry.body or "")
            rating = _MOOD_TO_RATING.get(entry.mood or "", 0)

            conn.execute(
                "INSERT INTO Entries (DiaryEntryId, Heading, Text, Rating, Latitude, Longitude) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entry_id, heading, text_html, rating, None, None),
            )

            for assoc in entry.tag_associations:
                tag = assoc.tag
                if not tag or not tag.name:
                    continue
                if tag.name not in tag_id_map:
                    cur = conn.execute("INSERT INTO Tags (Value) VALUES (?)", (tag.name,))
                    tag_id_map[tag.name] = cur.lastrowid  # type: ignore[assignment]
                conn.execute(
                    "INSERT OR IGNORE INTO EntryTags (DiaryEntryId, DiaryTagId) VALUES (?, ?)",
                    (entry_id, tag_id_map[tag.name]),
                )

        conn.commit()
        # Serialize to a binary SQLite file. We can't use Connection.serialize()
        # because the PyInstaller build swaps stdlib sqlite3 for pysqlite3
        # (for FTS5), and pysqlite3's Connection does not implement
        # serialize()/iterdump(). backup() to a file connection works in both
        # and yields a byte-identical SQLite database file.
        import tempfile
        from pathlib import Path as _Path

        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        try:
            with sqlite3.connect(tmp.name) as out:
                conn.backup(out)
            buf = io.BytesIO(_Path(tmp.name).read_bytes())
        finally:
            _Path(tmp.name).unlink(missing_ok=True)
    finally:
        conn.close()

    buf.seek(0)
    return StreamingResponse(
        buf,
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

    total_removed = 0
    for row in rows:
        id_list = [int(x) for x in row[2].split(",")]
        # Keep the first (oldest) id, delete the rest
        ids_to_delete = id_list[1:]
        for eid in ids_to_delete:
            from datetime import datetime, timezone

            await db.execute(
                text("UPDATE entries SET is_deleted = 1, deleted_at = :now WHERE id = :id"),
                {"now": datetime.now(timezone.utc), "id": eid},
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
        "entry_revisions",
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
            rows = conn.execute(
                "SELECT e.DiaryEntryId, e.Heading, e.Text, e.Rating, e.Latitude, e.Longitude FROM Entries e ORDER BY e.DiaryEntryId"
            ).fetchall()

            tag_rows = conn.execute(
                "SELECT et.DiaryEntryId, t.Value FROM EntryTags et JOIN Tags t ON et.DiaryTagId = t.DiaryTagId"
            ).fetchall()
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
                    logger.warning("Failed to parse Diarium date (ticks=%s)", ticks)
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
                    mood_val = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}.get(
                        int(rating)
                    )

                entries_data.append(
                    {
                        "entry_date": entry_date_str,
                        "title": heading,
                        "body": body_text,
                        "mood": mood_val,
                        "tags": entry_tags_map.get(row["DiaryEntryId"], []),
                        "latitude": row["Latitude"] if row["Latitude"] else None,
                        "longitude": row["Longitude"] if row["Longitude"] else None,
                    }
                )
            conn.close()
        finally:
            PathLib(tmp.name).unlink(missing_ok=True)

    else:
        # Small files — read into memory
        content = await file.read()

        if filename.endswith(".zip"):
            import zipfile as zf

            from app.services.importers import parse_dayone_zip

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
                                entries_data.append(_parse_diarium_json_entry(entry))
                            except Exception:
                                logger.warning("Failed to parse JSON entry from %s", jf)

                    if not json_files:
                        for n in names:
                            if n == "entries.json" or n == "diarium.json":
                                try:
                                    data = json.loads(z.read(n))
                                    if isinstance(data, list):
                                        for entry in data:
                                            entries_data.append(_parse_diarium_json_entry(entry))
                                except Exception:
                                    logger.warning("Failed to parse bulk JSON from %s", n)

                    md_files = sorted([n for n in names if n.endswith(".md")])
                    for mf in md_files:
                        raw = z.read(mf).decode("utf-8")
                        entry = _parse_markdown_entry(raw)
                        if entry:
                            entries_data.append(entry)

        elif filename.endswith(".csv"):
            from app.services.importers import parse_csv

            entries_data.extend(parse_csv(content.decode("utf-8", errors="replace")))

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
