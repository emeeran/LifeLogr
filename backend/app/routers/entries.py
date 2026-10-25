"""Journal entry route handlers."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import secrets
import tempfile
import uuid
import zipfile
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import or_ as sa_or
from sqlalchemy import select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.jobs import ProgressReporter, noop_reporter
from app.core.jobs import start_data_job as _start_data_job
from app.core.jobs import start_export_job
from app.models.entry import Entry
from app.models.media import Media
from app.models.tag import EntryTag
from app.schemas.entry import (
    CalendarEntryResponse,
    EntryCreate,
    EntryEventBrief,
    EntryListItem,
    EntryListResponse,
    EntryResponse,
    EntryUpdate,
    GeotagItem,
    GeotagResponse,
    ImportSkipReason,
    JournalStatsResponse,
    ResetRequest,
)
from app.schemas.tag import TagBrief
from app.services.enrichment_service import EnrichmentService
from app.services.entry_service import EntryService
from app.services.export_service import (
    ARCHIVE_FORMAT,
    ExportService,
    build_archive,
    build_diarium_database,
    build_daylio_csv,
)
from app.services.importers import (
    parse_csv,
    parse_dayone_zip,
    parse_diarium_json_entry,
    parse_diarium_sqlite,
    parse_markdown_entry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])

# Uploads are spooled to disk and rejected past this size instead of being
# ``await file.read()``-ed into memory unbounded (mirrors the backup import).
# Reuses the same setting as the archive importer so one knob governs both.
_MAX_IMPORT_MEMBER_BYTES = 64 * 1024 * 1024  # per-zip-member uncompressed cap
# How many per-record skip reasons to echo back (the ``skipped`` count stays
# exact; the detail list is truncated so a huge bad import can't blow up the
# response body).
_MAX_SKIP_REASONS = 100
# Rows per import transaction. Every row used to pay its own commit — an fsync
# each on SQLite — so a few-thousand-entry import took minutes and hammered the
# disk. 100 keeps any single transaction (and its lock) small while amortising
# the cost ~100x.
_IMPORT_COMMIT_CHUNK = 100


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
        tags=[
            TagBrief(
                id=a.tag.id,
                name=a.tag.name,
                is_tracker=a.tag.is_tracker,
                tracking_value=a.tracking_value,
            )
            for a in entry.tag_associations
            if a.tag
        ],
        events=[
            EntryEventBrief(id=ev.id, kind=ev.kind, content=ev.content, label=ev.label)
            for ev in entry.events
        ],
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


@router.get("/stats", response_model=JournalStatsResponse)
async def journal_stats(
    weeks: int = Query(12, ge=1, le=52),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Aggregates for the stats dashboard (streaks, words, weekly histogram,
    mood + media counts). Cached in memory; invalidated on entry mutations."""
    svc = EntryService(db)
    return await svc.get_stats(weeks=weeks)


@router.get("/on-this-day", response_model=list[CalendarEntryResponse])
async def on_this_day(db: AsyncSession = Depends(get_db)) -> Any:
    """Entries written on today's month/day in prior years (leap-day aware)."""
    from datetime import date as date_type

    svc = EntryService(db)
    return await svc.get_on_this_day(date_type.today())


@router.get("/geotags", response_model=GeotagResponse)
async def list_geotags(
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Entries with coordinates, for the map view.

    Excludes deleted entries and the (0, 0) null-island artifact. Only the
    lightweight projection is returned — bodies never leave the API for the
    map; the client links back to the entry for content.
    """
    from datetime import date as date_type

    filters = [
        Entry.is_deleted.is_(False),
        Entry.latitude.is_not(None),
        Entry.longitude.is_not(None),
        sa_or(Entry.latitude != 0, Entry.longitude != 0),
    ]
    if start_date:
        filters.append(Entry.entry_date >= date_type.fromisoformat(start_date))
    if end_date:
        filters.append(Entry.entry_date <= date_type.fromisoformat(end_date))

    total = (
        await db.execute(
            select(sa_func.count()).select_from(Entry).where(*filters)
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(Entry)
                .where(*filters)
                .options(selectinload(Entry.media))
                .order_by(Entry.entry_date.desc(), Entry.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    items = []
    for entry in rows:
        first_image = next(
            (m for m in entry.media if m.media_type == "image"), None
        )
        items.append(
            GeotagItem(
                id=entry.id,
                entry_date=entry.entry_date,
                title=entry.title,
                latitude=entry.latitude,
                longitude=entry.longitude,
                location_name=entry.location_name,
                is_encrypted=entry.is_encrypted,
                media_id=first_image.id if first_image else None,
            )
        )
    return GeotagResponse(items=items, total=total, offset=offset, limit=limit)


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


async def _export_entries(
    session: AsyncSession,
    start_date: str | None,
    end_date: str | None,
) -> list[Entry]:
    """Shared export query: non-deleted entries + tags + media, date-filtered."""
    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
            selectinload(Entry.media),
        )
        .order_by(Entry.entry_date, Entry.id)
    )
    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)
    result = await session.execute(q)
    return list(result.scalars().all())


def _build_markdown_zip_sync(entries: list[Entry], report=None) -> bytes:
    """Diarium-compatible markdown vault ZIP; *report* gets render/media ticks."""
    buf = io.BytesIO()
    media_total = sum(
        1
        for e in entries
        for m in e.media
        if (Path(settings.MEDIA_DIR) / m.storage_path).is_file()
    )
    media_done = 0
    if report is not None:
        report("render", 0, len(entries))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry_index, entry in enumerate(entries):
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
            # Media manifest — the files sit at media/{storage_path} in this
            # zip; `ref` is the id bodies reference as /api/v1/media/{ref}/file
            # so the importer can rewrite those links to the new ids.
            exportable_media = [
                m
                for m in entry.media
                if (Path(settings.MEDIA_DIR) / m.storage_path).is_file()
            ]
            if exportable_media:
                frontmatter += "media:\n"
                for media in exportable_media:
                    frontmatter += f"  - ref: {media.id}\n"
                    frontmatter += f"    path: media/{media.storage_path}\n"
                    frontmatter += f"    filename: {media.filename}\n"
                    frontmatter += f"    type: {media.media_type}\n"
            frontmatter += "---\n\n"

            # Same-day entries used to share one filename and overwrite each
            # other — suffix the id so every entry survives the round-trip.
            filename = f"entries/{entry.entry_date}-{entry.id}.md"
            zf.writestr(filename, frontmatter + entry.body)
            if report is not None:
                report("render", entry_index + 1, len(entries))

            # Include media files
            for media in entry.media:
                media_path = Path(settings.MEDIA_DIR) / media.storage_path
                if media_path.exists():
                    zf.write(str(media_path), f"media/{media.storage_path}")
                    media_done += 1
                    if report is not None:
                        report("media", media_done, media_total)

        # Add manifest
        manifest = {
            "format": "diarium-markdown",
            "version": "1.0",
            "exported_entries": len(entries),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    buf.seek(0)
    return buf.getvalue()


@router.get("/export/markdown")
async def export_markdown(
    background_tasks: BackgroundTasks,
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as Diarium-compatible markdown files in a .zip.

    Each entry becomes one .md file with YAML frontmatter (date, mood, tags).
    Media files are included in the zip alongside their entries.
    ``as_job=true`` returns ``{job_id}``; download the finished archive from
    ``GET /api/v1/jobs/{job_id}/result``.
    """
    if as_job:
        from app.core.database import async_session

        async def _build(report, session):
            entries = await _export_entries(session, start_date, end_date)
            return await asyncio.to_thread(_build_markdown_zip_sync, entries, report)

        return start_export_job(
            background_tasks, "export-markdown", "diarium-export.zip", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    # Zip assembly (deflate + copying every media file) is blocking — offload it.
    data = await asyncio.to_thread(_build_markdown_zip_sync, entries)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=diarium-export.zip"},
    )


@router.get("/export/html-zip")
async def export_html_zip(
    background_tasks: BackgroundTasks,
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as a styled HTML archive ZIP with media attachments.

    ``website/index.html`` renders every entry; media live under
    ``attachments/<date>/<filename>`` and are referenced relatively, so the
    unzipped folder browses offline like the Markdown vault export.
    ``as_job=true`` returns ``{job_id}``; download from
    ``GET /api/v1/jobs/{job_id}/result``.
    """
    from datetime import date as date_type

    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    if as_job:
        from app.core.database import async_session

        async def _build(report, session):
            return await ExportService(session).export_html_zip(start, end, report=report)

        return start_export_job(
            background_tasks, "export-html-zip", "lifelogr-export-html.zip", _build,
            session_factory=async_session,
        )

    payload = await ExportService(db).export_html_zip(start, end)
    buf = io.BytesIO(payload)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=lifelogr-export-html.zip"},
    )


@router.get("/export/diarium")
async def export_diarium(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries as a JSON array (date/text/heading/rating/tags).

    NOTE: Diarium itself has no generic JSON import — to move entries into
    Diarium use the Daylio CSV export (its documented migration format) or the
    .diary export (native backup restore). This file exists for tooling and
    re-import into LifeLogr (also via /import/file, where the importer accepts
    both this shape and Diarium's capitalized tick-keyed object model).
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

    def _build_json() -> bytes:
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
        return json.dumps(export_items, indent=2, ensure_ascii=False).encode("utf-8")

    # Serialising every full body is CPU-bound — offload it from the loop.
    buf = io.BytesIO(await asyncio.to_thread(_build_json))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=diarium-export.json"},
    )


@router.get("/export/daylio-csv")
async def export_daylio_csv(
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export entries as Daylio-format CSV — Diarium's supported migration import.

    Diarium reads this via Settings → Database → Migrate from other app → CSV
    (columns: full_date, date, weekday, time, mood, activities, note_title,
    note; mood words awful/bad/meh/good/rad). CSV carries text, mood and tags;
    use the .diary export for a full-fidelity backup restore instead.
    """
    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(selectinload(Entry.tag_associations).selectinload(EntryTag.tag))
        .order_by(Entry.entry_date, Entry.id)
    )
    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)
    result = await db.execute(q)
    entries = list(result.scalars().all())

    buf = io.BytesIO(await asyncio.to_thread(build_daylio_csv, entries))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="lifelogr-export.csv"'},
    )


@router.get("/export/archive")
async def export_archive(
    background_tasks: BackgroundTasks,
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries + media as the native LifeLogr archive ZIP.

    Full-fidelity, self-contained: ``lifelogr.json`` (entries with media
    metadata) plus every referenced media file under ``media/``. Re-imports
    via ``/import/file`` — media rows are recreated and the body's
    ``/api/v1/media/{id}/file`` links are rewritten to the new ids.
    ``as_job=true`` returns ``{job_id}``; download from
    ``GET /api/v1/jobs/{job_id}/result``.
    """
    if as_job:
        from app.core.database import async_session

        async def _build(report, session):
            entries = await _export_entries(session, start_date, end_date)
            return await asyncio.to_thread(build_archive, entries, report)

        return start_export_job(
            background_tasks, "export-archive", "lifelogr-archive.zip", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    buf = io.BytesIO(await asyncio.to_thread(build_archive, entries))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="lifelogr-archive.zip"'
        },
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

    def _build_json() -> bytes:
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
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    # Serialising every full body is CPU-bound — offload it from the loop.
    buf = io.BytesIO(await asyncio.to_thread(_build_json))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=lifelogr-export.json"},
    )


# .NET DateTime ticks for 0001-01-01 (the epoch Diarium's DiaryEntryId is based on).
@router.get("/export/diarium-db")
async def export_diarium_db(
    background_tasks: BackgroundTasks,
    start_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as a Diarium-native .diary SQLite database.

    Produces the real Diarium schema (Entries keyed by .NET DateTime ticks,
    Tags, EntryTags) so the file can be opened/imported directly by the
    Diarium app or re-imported here via the .diary importer. Media
    attachments are embedded as real Media rows (bytes + name + order).
    ``as_job=true`` returns ``{job_id}``; download from
    ``GET /api/v1/jobs/{job_id}/result``.
    """
    if as_job:
        from app.core.database import async_session

        async def _build(report, session):
            entries = await _export_entries(session, start_date, end_date)
            return await build_diarium_database(entries, report=report)

        return start_export_job(
            background_tasks, "export-diary", "lifelogr-export.diary", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    # build_diarium_database offloads its SQLite build to a worker thread.
    data = await build_diarium_database(entries)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="lifelogr-export.diary"'},
    )


@router.post("/deduplicate", response_model=dict)
async def deduplicate_entries(db: AsyncSession = Depends(get_db)) -> Any:
    """Find and soft-delete duplicate entries.

    Entries are considered duplicates if they share the same entry_date and
    normalized body (newlines/tabs/CR → spaces, space runs collapsed, trimmed,
    case-insensitive). For each group the **oldest** entry — the lowest ``id``,
    an explicit, order-independent rule — is kept and the rest are soft-deleted.
    """
    from datetime import datetime, timezone

    from sqlalchemy import bindparam, text

    # One deterministic statement: normalize, then rank each duplicate group by
    # id and keep rn = 1 (the lowest id = oldest). The previous GROUP_CONCAT(id)
    # version depended on SQLite's unspecified concatenation order to pick the
    # survivor, and collapsed only newlines, not space runs.
    result = await db.execute(
        text("""
        WITH norm AS (
            SELECT id,
                   entry_date,
                   LOWER(TRIM(
                       REPLACE(
                           REPLACE(
                               REPLACE(
                                   REPLACE(
                                       REPLACE(
                                           REPLACE(
                                               REPLACE(body, CHAR(13), '')
                                           , CHAR(10), ' ')
                                       , CHAR(9), ' ')
                                   , CHAR(12), ' ')
                               , '  ', ' ')
                           , '  ', ' ')
                       , '  ', ' '))) AS norm_body
            FROM entries
            WHERE is_deleted = 0
        ),
        ranked AS (
            SELECT entry_date,
                   norm_body,
                   id,
                   ROW_NUMBER() OVER (
                       PARTITION BY entry_date, norm_body ORDER BY id ASC
                   ) AS rn
            FROM norm
            WHERE norm_body <> ''
        )
        SELECT entry_date, norm_body, id FROM ranked WHERE rn > 1
        ORDER BY entry_date, norm_body, id
    """)
    )
    rows = result.fetchall()
    if not rows:
        return {"groups_found": 0, "duplicates_removed": 0}

    ids_to_delete = [int(row[2]) for row in rows]
    groups_found = len({(str(row[0]), str(row[1])) for row in rows})

    # One bulk UPDATE + a single commit (previously one UPDATE per id).
    await db.execute(
        text("UPDATE entries SET is_deleted = 1, deleted_at = :now WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"now": datetime.now(timezone.utc), "ids": ids_to_delete},
    )

    await db.commit()
    from app.services.entry_service import invalidate_stats_cache

    invalidate_stats_cache()
    return {"groups_found": groups_found, "duplicates_removed": len(ids_to_delete)}


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


# Configuration / bookkeeping tables a content reset must NOT touch: the
# migration stamp, SQLite internals, provider credentials, and the backup
# configuration + schedule (wiping those would silently disable backups).
_RESET_PROTECTED_TABLES = frozenset(
    {
        "_schema_meta",
        "alembic_version",
        "ai_providers",
        "backup_config",
        "backup_schedule",
        "backup_snapshots",
        "sync_status",
        "daily_prompts",
        "reminders",
        "templates",
    }
)


def _reset_table_names() -> list[str]:
    """Content tables to wipe, derived from the ORM metadata.

    ``sorted_tables`` lists referenced (parent) tables first, so it is reversed
    to delete children (``entry_tags``, ``media``, …) before the rows they point
    at. Deriving the list keeps the wipe accurate as models evolve — the old
    hand-written list had already drifted (it skipped ``note_pages`` and the
    per-entry ``entry_embeddings``/``entry_sentiments``/``entry_prompts`` rows,
    and it wiped notes while the docstring claimed entries/tags only).
    """
    return [
        table.name
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in _RESET_PROTECTED_TABLES
    ]


@router.post("/reset", response_model=dict)
async def reset_database(payload: ResetRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Delete **all** user content: entries, tags, notes, folders, and their
    attachments/derived rows. Irreversible.

    Only configuration survives (AI providers, backup config/schedule,
    templates, prompts, reminders) plus internal bookkeeping tables.

    Guarded at the middleware layer (see ``main.py``): when ``API_TOKEN`` is set
    the shared-token gate requires a bearer token on every ``/api/*`` call,
    including this one; the destructive-endpoint guard additionally throttles
    this path (5/minute, always on) and rejects any Origin the deployment does
    not itself use — so a hostile page on another local port cannot drive a
    cross-site wipe the way it could against the ordinary loopback-origin rule.
    The bundled frontend sends only ``{"confirm": "RESET"}``, so the
    confirmation stays a body field rather than a handshake nonce.
    """
    if not secrets.compare_digest(payload.confirm, "RESET"):
        raise HTTPException(
            status_code=400,
            detail='Confirmation required: send {"confirm": "RESET"} to wipe the database.',
        )
    from sqlalchemy import text

    for table in _reset_table_names():
        await db.execute(text(f"DELETE FROM {table}"))
    try:
        await db.execute(text("DELETE FROM sqlite_sequence"))
    except Exception:
        logger.debug("sqlite_sequence cleanup skipped (may not exist)")
    await db.commit()
    return {"status": "ok", "message": "Database cleared."}


@router.post("/import")
async def import_entries(
    background_tasks: BackgroundTasks,
    payload: list[dict[str, Any]],
    as_job: bool = Query(False, description="Insert as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Import entries from a JSON array. Each entry needs at least entry_date and body.

    ``as_job=true`` runs the insert loop as a job (202 ``{job_id}``) — poll
    ``GET /api/v1/jobs/{job_id}`` for insert progress.
    """
    if not as_job:
        return await _run_json_entry_import(db, payload)

    def _runner(job_report: ProgressReporter) -> Awaitable[str]:
        async def _run() -> str:
            from app.core.database import async_session

            async with async_session() as session:
                result = await _run_json_entry_import(session, payload, job_report)
                return f"Imported {result['imported']}, skipped {result['skipped']}"

        return _run()

    return _start_data_job(background_tasks, "import-entries", _runner)


async def _run_json_entry_import(
    db: AsyncSession,
    payload: list[dict[str, Any]],
    report: ProgressReporter = noop_reporter,
) -> dict[str, Any]:
    """Insert a plain JSON entry array (no media/trackers/dedup-signatures)."""
    from app.models.tag import Tag

    svc = EntryService(db)
    imported = 0
    skipped = 0
    skip_reasons: list[ImportSkipReason] = []
    tag_cache: dict[str, Tag] = {}
    # (entry_id, title, body) awaiting enrichment — queued only once the batch
    # they belong to is actually committed, because the enrichment workers use
    # their own DB sessions and would neither see nor be able to update rows
    # that are still uncommitted.
    to_enrich: list[tuple[int, str | None, str]] = []
    since_commit = 0

    async def _commit_batch() -> None:
        """Commit the in-flight chunk, then release its enrichment jobs."""
        if not imported and not to_enrich:
            return
        await db.commit()
        for entry_id, title, body in to_enrich:
            EnrichmentService.schedule(entry_id, title, body)
        to_enrich.clear()

    async def _tag_ids_for(names: list[Any]) -> list[int]:
        """Resolve tag names to ids, creating any that don't exist yet."""
        ids: list[int] = []
        for name in names:
            if not name:
                continue
            tag = tag_cache.get(name)
            if tag is None:
                res = await db.execute(select(Tag).where(Tag.name == name))
                tag = res.scalar_one_or_none()
                if tag is None:
                    tag = Tag(name=name)
                    db.add(tag)
                    await db.flush()
                tag_cache[name] = tag
            ids.append(tag.id)
        return ids

    total = len(payload)
    report("insert", 0, total)
    for idx, item in enumerate(payload):
        entry_date = item.get("entry_date")
        body = item.get("body")
        if not entry_date or not body:
            skipped += 1
            skip_reasons = _record_skip(
                skip_reasons,
                idx,
                str(entry_date or "") or None,
                item.get("title"),
                "missing entry_date or body",
            )
            report("insert", idx + 1, total)
            continue
        try:
            data = EntryCreate(
                entry_date=entry_date,
                title=item.get("title"),
                body=body,
                mood=item.get("mood"),
                tag_ids=await _tag_ids_for(item.get("tags") or []),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
            )
            entry = await svc.create(data, commit=False)
            if not entry.is_encrypted:
                to_enrich.append((entry.id, entry.title, entry.body))
            imported += 1
        except Exception as e:
            logger.warning("Failed to import entry (date=%s): %s", entry_date, e)
            skipped += 1
            skip_reasons = _record_skip(
                skip_reasons, idx, str(entry_date), item.get("title"), f"error: {e}"
            )
        report("insert", idx + 1, total)
        since_commit += 1
        if since_commit >= _IMPORT_COMMIT_CHUNK:
            await _commit_batch()
            since_commit = 0
    await _commit_batch()
    report("enrich", 0, total)
    return {"imported": imported, "skipped": skipped, "skip_reasons": skip_reasons}


def _record_skip(
    reasons: list[ImportSkipReason],
    index: int,
    entry_date: str | None,
    title: str | None,
    reason: str,
) -> list[ImportSkipReason]:
    """Append a skip reason (capped) and log it, so failures aren't silent."""
    if len(reasons) < _MAX_SKIP_REASONS:
        reasons.append(
            ImportSkipReason(
                index=index,
                entry_date=entry_date,
                title=(title[:120] if title else None),
                reason=reason[:300],
            )
        )
    logger.info("Import skipped record %d (date=%s): %s", index, entry_date, reason)
    return reasons


async def _spool_upload(file: UploadFile, max_bytes: int) -> Path:
    """Spool an upload to a temp file, aborting past ``max_bytes`` with 413.

    ``await file.read()`` materialises the whole payload in memory; streaming in
    1 MiB chunks bounds the request's footprint and enforces a hard cap (same
    pattern as the backup importer).
    """
    upload = tempfile.NamedTemporaryFile(
        delete=False, suffix=Path(file.filename or "import").suffix[:16] or ".bin"
    )
    path = Path(upload.name)
    written = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Import file exceeds the {max_bytes}-byte limit.",
                )
            upload.write(chunk)
        upload.flush()
        upload.close()
    except Exception:
        upload.close()
        path.unlink(missing_ok=True)
        raise
    return path


def _zip_members(z: zipfile.ZipFile) -> list[str]:
    """Names of the archive's file members (directories excluded)."""
    return [n for n in z.namelist() if not n.endswith("/")]


def _read_member(z: zipfile.ZipFile, name: str) -> bytes:
    """Read one zip member, refusing decompression-bomb members up front.

    ``ZipInfo.file_size`` is the declared uncompressed size, so checking it
    before ``read()`` bounds the memory a single member can consume.
    """
    info = z.getinfo(name)
    if info.file_size > _MAX_IMPORT_MEMBER_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Archive member {name!r} is {info.file_size} bytes uncompressed, "
                f"above the {_MAX_IMPORT_MEMBER_BYTES}-byte limit."
            ),
        )
    return z.read(name)


# ── Import-side media attachment ─────────────────────────────────────────────
# Bodies embed media as URLs of the form /api/v1/media/{id}/file. On import the
# media rows get NEW ids, so every parsed entry may carry a `media` payload
# list; after the rows are created the body's URLs are rewritten to point at
# the fresh ids (keyed by the export-time `ref` id).
_MEDIA_URL_RE = re.compile(r"/api/v1/media/(\d+)/file")
_VALID_IMPORT_MEDIA_TYPES = {"image", "video", "audio", "document"}


def _remap_media_urls(body: str, ref_map: dict[int, int]) -> str:
    """Rewrite /api/v1/media/{old}/file references to their imported ids."""
    if not ref_map:
        return body
    return _MEDIA_URL_RE.sub(
        lambda m: f"/api/v1/media/{ref_map[int(m.group(1))]}/file", body
    )


async def _attach_imported_media(
    db: AsyncSession, entry_row: Entry, media_items: list[dict[str, Any]]
) -> dict[int, int]:
    """Persist parsed media payloads as Media rows for *entry_row*.

    Payloads come from the native archive (bytes read from the ZIP), Diarium
    ``.diary`` Media blobs, or Markdown ZIP members — each item is
    ``{filename, media_type, data, caption?, is_inline?, ref?}``. Returns
    ``{ref: new_id}`` for body-URL remapping. Bytes go through the same
    signature and size checks as uploads: an import path must never become a
    way to smuggle blocked file types past MediaService.
    """
    ref_map: dict[int, int] = {}
    for item in media_items:
        data = item.get("data") or b""
        if not data:
            continue
        filename = (item.get("filename") or "attachment.bin").strip() or "attachment.bin"
        if len(data) > settings.MAX_MEDIA_SIZE_BYTES:
            logger.warning(
                "Import media %s (%d bytes) exceeds the per-file cap — skipped",
                filename,
                len(data),
            )
            continue
        try:
            from app.services.media_service import MediaService

            MediaService._check_signature(data[:64], filename)
        except Exception as e:
            logger.warning("Import media %s blocked: %s", filename, e)
            continue
        media_type = (item.get("media_type") or "document").lower()
        if media_type not in _VALID_IMPORT_MEDIA_TYPES:
            media_type = "document"
        ext = Path(filename).suffix.lower()
        stored_name = f"{uuid.uuid4()}{ext}"
        dest = settings.MEDIA_DIR / f"{media_type}s" / stored_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        row = Media(
            entry_id=entry_row.id,
            filename=filename,
            media_type=media_type,
            file_size=len(data),
            storage_path=f"{media_type}s/{stored_name}",
            caption=item.get("caption") or None,
            is_inline=bool(item.get("is_inline")),
        )
        db.add(row)
        await db.flush()
        ref = item.get("ref")
        if ref is not None:
            try:
                ref_map[int(ref)] = row.id
            except (TypeError, ValueError):
                pass
    return ref_map


async def _attach_imported_events(
    db: AsyncSession, entry_row: Entry, events: list[dict[str, Any]]
) -> None:
    """Persist parsed Diarium Events rows as EntryEvent rows for *entry_row*.

    Each item is ``{kind, content, label?}`` (kind "weather" or
    "unknown:<n>"); blank content is dropped, everything else is kept
    verbatim so unknown vendor event types survive a round trip.
    """
    from app.models.entry_event import EntryEvent

    for ev in events:
        content = str(ev.get("content") or "").strip()
        if not content:
            continue
        db.add(
            EntryEvent(
                entry_id=entry_row.id,
                kind=str(ev.get("kind") or "unknown:?")[:50],
                content=content[:500],
                label=(str(ev["label"])[:255] if ev.get("label") else None),
            )
        )
    await db.flush()


@router.post("/import/file")
async def import_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    skip_duplicates: bool = Query(
        True, description="Skip entries already present (same date + body)"
    ),
    as_job: bool = Query(False, description="Insert as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Import entries from an uploaded file (ZIP, JSON, or Diarium .diary).

    The upload is spooled to a temp file behind a hard size cap rather than
    read wholesale into memory.

    Supports:
    - Diarium .diary SQLite database
    - Day One JSON export ZIP (Journal.json)
    - Diarium JSON export (array of entries with date/html/heading/tags/rating)
    - Markdown ZIP (entries/*.md with YAML frontmatter: date, mood, tags)
    - CSV

    Parsing happens synchronously (the caller tracks the upload itself);
    ``as_job=true`` runs the insert loop as a job and returns 202
    ``{job_id}`` — poll ``GET /api/v1/jobs/{job_id}`` for insert progress.
    """
    filename = file.filename or ""

    entries_data: list[dict[str, Any]] = []

    upload_path = await _spool_upload(file, settings.MAX_IMPORT_SIZE_BYTES)
    try:
        if filename.endswith(".diary"):
            # Diarium .diary SQLite database — parsing lives in the importers service.
            entries_data.extend(parse_diarium_sqlite(upload_path.read_bytes()))
        else:
            content = upload_path.read_bytes()

            if filename.endswith(".zip"):
                # Day One exports carry Journal.json — detect and handle first.
                is_dayone = False
                zip_names: list[str] = []
                try:
                    with zipfile.ZipFile(upload_path, "r") as z:
                        zip_names = _zip_members(z)
                        is_dayone = any(n.endswith("Journal.json") for n in zip_names)
                except zipfile.BadZipFile:
                    pass

                if is_dayone:
                    entries_data.extend(parse_dayone_zip(content))
                elif "lifelogr.json" in zip_names:
                    # Native archive: lifelogr.json + media/ members. Each
                    # entry's media bytes are pulled here so the shared loop
                    # can persist them and rewrite body URLs.
                    with zipfile.ZipFile(upload_path, "r") as z:
                        media_names = set(zip_names)
                        doc = json.loads(_read_member(z, "lifelogr.json"))
                        if doc.get("format") != ARCHIVE_FORMAT:
                            raise HTTPException(
                                status_code=422,
                                detail="Not a LifeLogr archive (unexpected format field)",
                            )
                        for item in doc.get("entries", []):
                            media_items = []
                            for m in item.get("media", []):
                                member = m.get("path", "")
                                media_items.append(
                                    {
                                        "filename": m.get("filename"),
                                        "media_type": m.get("media_type"),
                                        "caption": m.get("caption"),
                                        "is_inline": m.get("is_inline"),
                                        "ref": m.get("ref"),
                                        "data": (
                                            _read_member(z, member)
                                            if member in media_names
                                            else b""
                                        ),
                                    }
                                )
                            entries_data.append(
                                {
                                    "entry_date": item.get("entry_date"),
                                    "title": item.get("title"),
                                    "body": item.get("body"),
                                    "mood": item.get("mood"),
                                    "tags": item.get("tags", []),
                                    "latitude": item.get("latitude"),
                                    "longitude": item.get("longitude"),
                                    "media": media_items,
                                }
                            )
                else:
                    with zipfile.ZipFile(upload_path, "r") as z:
                        names = _zip_members(z)

                        json_files = [
                            n for n in names if n.endswith(".json") and n != "manifest.json"
                        ]
                        if json_files:
                            for jf in json_files:
                                try:
                                    entry = json.loads(_read_member(z, jf))
                                    entries_data.append(parse_diarium_json_entry(entry))
                                except HTTPException:
                                    raise
                                except Exception:
                                    logger.warning("Failed to parse JSON entry from %s", jf)

                        if not json_files:
                            for n in names:
                                if n == "entries.json" or n == "diarium.json":
                                    try:
                                        data = json.loads(_read_member(z, n))
                                        if isinstance(data, list):
                                            for entry in data:
                                                entries_data.append(
                                                    parse_diarium_json_entry(entry)
                                                )
                                    except HTTPException:
                                        raise
                                    except Exception:
                                        logger.warning("Failed to parse bulk JSON from %s", n)

                        md_files = sorted(n for n in names if n.endswith(".md"))
                        for mf in md_files:
                            raw = _read_member(z, mf).decode("utf-8")
                            entry = parse_markdown_entry(raw)
                            if entry:
                                # Resolve the frontmatter media manifest against
                                # this zip's media/ members.
                                for m in entry.get("media", []):
                                    member = m.get("path", "")
                                    m["data"] = (
                                        _read_member(z, member) if member in names else b""
                                    )
                                entries_data.append(entry)

            elif filename.endswith(".csv"):
                entries_data.extend(parse_csv(content.decode("utf-8", errors="replace")))

            elif filename.endswith(".json"):
                data = json.loads(content)
                items = data if isinstance(data, list) else data.get("entries", [])
                for item in items:
                    try:
                        parsed = parse_diarium_json_entry(item)
                        if not parsed.get("body") and not parsed.get("entry_date"):
                            parsed = {
                                "entry_date": item.get("entry_date") or item.get("date", "")[:10],
                                "title": item.get("title") or item.get("heading"),
                                "body": item.get("body", ""),
                                "mood": item.get("mood"),
                                "tags": item.get("tags", []),
                                "latitude": item.get("latitude"),
                                "longitude": item.get("longitude"),
                            }
                    except Exception as e:
                        # A malformed record must not abort the whole import: it
                        # becomes a placeholder that the loop below skips, with
                        # the reason surfaced in the response.
                        logger.warning("Skipping malformed import record: %s", e)
                        parsed = {
                            "entry_date": "",
                            "body": "",
                            "title": item.get("title") if isinstance(item, dict) else None,
                            "error": f"unparsable record: {e}",
                        }
                    entries_data.append(parsed)
    finally:
        upload_path.unlink(missing_ok=True)

    if not as_job:
        return await _run_entry_import(db, entries_data, skip_duplicates)

    def _runner(job_report: ProgressReporter) -> Awaitable[str]:
        async def _run() -> str:
            from app.core.database import async_session

            async with async_session() as session:
                result = await _run_entry_import(
                    session, entries_data, skip_duplicates, job_report
                )
                return f"Imported {result['imported']}, skipped {result['skipped']}"

        return _run()

    return _start_data_job(background_tasks, "import-entries", _runner)


async def _run_entry_import(
    db: AsyncSession,
    entries_data: list[dict[str, Any]],
    skip_duplicates: bool,
    report: ProgressReporter = noop_reporter,
) -> dict[str, Any]:
    """Insert parsed entries: dedup, tags/trackers, media, events, enrichment.

    Shared by /import/file's sync and job paths (and shaped for reuse); *report*
    phases: insert (done/total per parsed record).
    """
    import hashlib
    from datetime import date as date_type

    from sqlalchemy import func as sa_func

    from app.models.tag import Tag

    svc = EntryService(db)
    # Pre-load all existing tags to avoid N+1 lookups
    existing_tags_result = await db.execute(select(Tag))
    tag_cache: dict[str, Tag] = {t.name: t for t in existing_tags_result.scalars().all()}

    # Duplicate detection: (entry_date, sha256(body[:1000] + mood)) of existing
    # rows. Only the first 1000 body characters are pulled from SQL (``substr``),
    # so the full body of every entry is never materialised just to fingerprint
    # it. The mood suffix keeps same-day mood-only check-ins distinct.
    existing_sigs: set[tuple[str, str]] = set()
    if skip_duplicates:
        _rows = await db.execute(
            select(
                Entry.entry_date,
                sa_func.substr(Entry.body, 1, 1000),
                Entry.mood,
            ).where(~Entry.is_deleted)
        )
        for _ed, _prefix, _mood in _rows.all():
            existing_sigs.add(
                (
                    str(_ed),
                    hashlib.sha256(
                        ((_prefix or "") + "\x00" + (_mood or "")).encode()
                    ).hexdigest(),
                )
            )

    imported = 0
    skipped = 0
    skip_reasons: list[ImportSkipReason] = []
    since_commit = 0
    # Enrichment is queued only for rows that are already committed — the
    # workers use their own sessions and can't see uncommitted rows.
    to_enrich: list[tuple[int, str | None, str]] = []

    async def _commit_batch() -> None:
        """Commit the in-flight chunk, then release its enrichment jobs."""
        if not imported and not to_enrich:
            return
        await db.commit()
        for entry_id, title, body in to_enrich:
            EnrichmentService.schedule(entry_id, title, body)
        to_enrich.clear()

    total = len(entries_data)
    report("dedup", 0, total)
    report("insert", 0, total)
    for idx, entry in enumerate(entries_data):
        # An empty body is legal when the entry carries media (photo-only
        # Diarium entries) or a mood (Daylio mood-only check-ins); only truly
        # empty records are skipped.
        if not entry.get("entry_date") or (
            not entry.get("body") and not entry.get("media") and not entry.get("mood")
        ):
            skipped += 1
            skip_reasons = _record_skip(
                skip_reasons,
                idx,
                entry.get("entry_date") or None,
                entry.get("title"),
                str(entry.get("error") or "missing entry_date or body"),
            )
            report("insert", idx + 1, total)
            continue
        try:
            ed = entry["entry_date"]
            if isinstance(ed, str):
                ed = date_type.fromisoformat(ed[:10])

            # The dedup fingerprint includes the mood so two same-day
            # mood-only check-ins with different moods don't collapse.
            sig = (
                str(ed),
                hashlib.sha256(
                    ((entry["body"] or "")[:1000] + "\x00" + (entry.get("mood") or "")).encode()
                ).hexdigest(),
            )
            if skip_duplicates and sig in existing_sigs:
                skipped += 1
                skip_reasons = _record_skip(
                    skip_reasons, idx, str(ed), entry.get("title"), "duplicate of existing entry"
                )
                report("insert", idx + 1, total)
                continue

            # Resolve tag names to IDs (create tags if needed)
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

            # Tracker tags (Diarium Tags.Type=2): create/flag before the entry's
            # associations are written, then stamp the verbatim reading on the
            # association row afterwards.
            trackers = entry.get("trackers") or []
            tracker_names: list[str] = []
            for tr in trackers:
                name = (tr.get("name") or "").strip()
                if not name:
                    continue
                tracker_names.append(name)
                tag = tag_cache.get(name)
                if tag is None:
                    tag = Tag(name=name, is_tracker=True)
                    tag_cache[name] = tag
                    db.add(tag)
                elif not tag.is_tracker:
                    tag.is_tracker = True
            if trackers:
                await db.flush()

            all_tag_names = list(entry.get("tags", [])) + tracker_names
            tag_ids = [tag_cache[tn].id for tn in all_tag_names if tn and tag_cache.get(tn)]

            data = EntryCreate(
                entry_date=ed,
                title=entry.get("title"),
                body=entry["body"],
                mood=entry.get("mood"),
                tag_ids=tag_ids,
                latitude=entry.get("latitude"),
                longitude=entry.get("longitude"),
            )
            created = await svc.create(data, commit=False)
            media_items = entry.get("media") or []
            if media_items:
                ref_map = await _attach_imported_media(db, created, media_items)
                # Bodies reference media by URL; the imported rows have new
                # ids, so rewrite before anything (incl. enrichment) sees it.
                if ref_map and created.body:
                    created.body = _remap_media_urls(created.body, ref_map)
            events_items = entry.get("events") or []
            if events_items:
                await _attach_imported_events(db, created, events_items)
            if trackers:
                # One bulk UPDATE — the associations were flushed inside
                # svc.create; touching the ORM collection here would lazy-load
                # outside a greenlet.
                from sqlalchemy import update

                from app.models.tag import EntryTag

                for tr in trackers:
                    name = (tr.get("name") or "").strip()
                    value = tr.get("value")
                    if not name or value is None:
                        continue
                    await db.execute(
                        update(EntryTag)
                        .where(
                            EntryTag.entry_id == created.id,
                            EntryTag.tag_id == tag_cache[name].id,
                        )
                        .values(tracking_value=str(value)[:500])
                    )
            if not created.is_encrypted:
                to_enrich.append((created.id, created.title, created.body))
            existing_sigs.add(sig)
            imported += 1
        except Exception as e:
            logger.warning(
                "Failed to import entry (date=%s): %s", entry.get("entry_date"), e, exc_info=True
            )
            skipped += 1
            skip_reasons = _record_skip(
                skip_reasons,
                idx,
                str(entry.get("entry_date") or "") or None,
                entry.get("title"),
                f"error: {e}",
            )
        report("insert", idx + 1, total)
        since_commit += 1
        if since_commit >= _IMPORT_COMMIT_CHUNK:
            await _commit_batch()
            since_commit = 0

    await _commit_batch()
    report("enrich", 0, total)
    return {"imported": imported, "skipped": skipped, "skip_reasons": skip_reasons}
