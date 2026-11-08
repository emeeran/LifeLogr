"""Journal entry route handlers."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import secrets
import uuid
import zipfile
from collections import Counter
from collections.abc import Awaitable
from datetime import date, datetime
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
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import or_ as sa_or
from sqlalchemy import select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.exceptions import MediaSizeError
from app.core.jobs import ProgressReporter, noop_reporter
from app.core.jobs import start_data_job as _start_data_job
from app.core.jobs import start_export_job
from app.routers._params import parse_tag_ids
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
    TrashItemResponse,
    TrashListResponse,
)
from app.schemas.tag import TagBrief
from app.services.enrichment_service import EnrichmentService
from app.services.entry_service import EntryService
from app.services.media_service import check_signature, spool_upload
from app.services.export_service import (
    ARCHIVE_FORMAT,
    ExportService,
    build_markdown_zip,
    build_archive,
    build_daylio_csv,
    build_dayone_zip,
    build_diarium_database,
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

# Import modes. "merge" reconciles with rows already imported (source identity
# first, date+body prefix as the fallback) and fills in missing media/events;
# "append" keeps the old always-insert behaviour.
_IMPORT_MODES = ("merge", "append")


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
    year: int | None = Query(None, ge=1, le=9999),
    month: int | None = Query(None, ge=1, le=12),
    template_id: int | None = Query(None, description="Only entries created from this template"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List entries with optional filters and pagination."""
    svc = EntryService(db)
    parsed_tag_ids = parse_tag_ids(tag_ids)
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


@router.get("/trash", response_model=TrashListResponse)
async def list_trash(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List soft-deleted entries (restorable trash), newest deletion first."""
    svc = EntryService(db)
    entries, total = await svc.list_trash(offset, limit)
    snippets = await svc.body_snippets([e.id for e in entries])
    return TrashListResponse(
        items=[
            TrashItemResponse(
                id=e.id,
                entry_date=e.entry_date,
                title=e.title,
                body_snippet=snippets.get(e.id, ""),
                mood=e.mood,
                is_encrypted=e.is_encrypted,
                tags=[TagBrief(id=a.tag.id, name=a.tag.name) for a in e.tag_associations if a.tag],
                media_count=len(e.media),
                has_recording=len(e.recordings) > 0,
                deleted_at=e.deleted_at or e.updated_at,
                created_at=e.created_at,
            )
            for e in entries
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/calendar/{year}/{month}", response_model=list[CalendarEntryResponse])
async def calendar_view(
    year: int = PathParam(ge=1, le=9999),
    month: int = PathParam(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Any:
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
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Entries with coordinates, for the map view.

    Excludes deleted entries and the (0, 0) null-island artifact. Only the
    lightweight projection is returned — bodies never leave the API for the
    map; the client links back to the entry for content.
    """

    filters = [
        Entry.is_deleted.is_(False),
        Entry.latitude.is_not(None),
        # GeotagItem (and Leaflet) need both coordinates; a lat-only row would
        # break the map client anyway, so the filter matches the contract.
        Entry.longitude.is_not(None),
        sa_or(Entry.latitude != 0, Entry.longitude != 0),
    ]
    if start_date:
        filters.append(Entry.entry_date >= start_date)
    if end_date:
        filters.append(Entry.entry_date <= end_date)

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
        # The query filters both coordinates non-null (and the map client
        # requires them) — narrow so the strict schema constructor type-checks.
        assert entry.latitude is not None and entry.longitude is not None
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
    start_date: date | None,
    end_date: date | None,
    *,
    only_new: bool = False,
) -> list[Entry]:
    """Shared export query: non-deleted entries + tags + media, date-filtered.

    ``only_new`` keeps just the entries a Diarium push has not covered yet: rows
    with no source identity, on days Diarium does not already have. Days it does
    have are skipped because Diarium's migration import matches on date/time —
    pushing a date-only entry onto a day it already holds would duplicate it.
    """
    q = (
        select(Entry)
        .where(Entry.is_deleted.is_(False))
        .options(
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
            selectinload(Entry.media),
            selectinload(Entry.events),
        )
        .order_by(Entry.entry_date, Entry.id)
    )
    if only_new:
        diarium_days = select(Entry.entry_date).where(
            Entry.external_id.is_not(None), Entry.is_deleted.is_(False)
        )
        q = q.where(Entry.external_id.is_(None), Entry.entry_date.not_in(diarium_days))
    if start_date:
        q = q.where(Entry.entry_date >= start_date)
    if end_date:
        q = q.where(Entry.entry_date <= end_date)
    result = await session.execute(q)
    return list(result.scalars().all())


async def _run_note_archive_import(
    db: AsyncSession, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Restore the notes carried in a native archive (v2) after the entries."""
    from app.services.notes_export_service import NotesExportService

    result = await NotesExportService(db)._import_items(items)
    logger.info(
        "Archive notes import: %d imported, %d skipped",
        result["imported"],
        result["skipped"],
    )
    return result


async def _load_archive_notes(session: AsyncSession) -> list[dict[str, Any]]:
    """Serialize non-deleted notes for the native archive (v2).

    Mirrors NotesExportService.export_json's item shape (encrypted notes keep
    their placeholder body) plus a ``media`` list whose ``path`` members point
    at ``media/<storage_path>`` in the archive; ``ref`` is the export-time id
    the importer rewrites body URLs to.
    """
    from app.models.note import Note, NoteTag
    from app.services.notes_export_service import ENCRYPTED_PLACEHOLDER

    res = await session.execute(
        select(Note)
        .where(Note.is_deleted.is_(False))
        .options(
            selectinload(Note.folder),
            selectinload(Note.tag_associations).selectinload(NoteTag.tag),
            selectinload(Note.pages),
            selectinload(Note.media),
        )
        .order_by(Note.created_at)
    )
    notes = []
    for n in res.scalars():
        notes.append(
            {
                "title": n.title,
                "body": ENCRYPTED_PLACEHOLDER if n.is_encrypted else (n.body or ""),
                "is_encrypted": n.is_encrypted,
                "is_pinned": n.is_pinned,
                "color": n.color,
                "folder": n.folder.name if n.folder else None,
                "tags": [nt.tag.name for nt in n.tag_associations],
                "pages": [{"title": p.title, "body": p.body} for p in n.pages],
                "media": [
                    {
                        "ref": m.id,
                        "path": f"media/{m.storage_path}",
                        "filename": m.filename,
                        "media_type": m.media_type,
                        "caption": m.caption,
                    }
                    for m in n.media
                    # NOTE: encrypted notes' media stays here **as ciphertext** —
                    # this is the native backup format; restore needs rows and
                    # files (design §9). Share exports omit them instead.
                    if (settings.MEDIA_DIR / m.storage_path).is_file()
                ],
            }
        )
    return notes


def _staged_file_response(path: Path, filename: str, media_type: str) -> FileResponse:
    """Serve a staged export file, unlinking it after the response is sent.

    The media-heavy export builders write archives straight to DATA_DIR/tmp
    (never in RAM); this is the matching serve-and-cleanup half.
    """
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(path.unlink, True),
    )


@router.get("/export/markdown")
async def export_markdown(
    background_tasks: BackgroundTasks,
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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

        async def _build(report: ProgressReporter, session: AsyncSession) -> Path:
            entries = await _export_entries(session, start_date, end_date)
            return await asyncio.to_thread(build_markdown_zip, entries, report)

        return start_export_job(
            background_tasks, "export-markdown", "diarium-export.zip", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    # Zip assembly (deflate + copying every media file) is blocking — offload it.
    staged = await asyncio.to_thread(build_markdown_zip, entries)
    return _staged_file_response(staged, "diarium-export.zip", "application/zip")


@router.get("/export/html-zip")
async def export_html_zip(
    background_tasks: BackgroundTasks,
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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

    start = start_date
    end = end_date

    if as_job:
        from app.core.database import async_session

        async def _build(report: ProgressReporter, session: AsyncSession) -> Path:
            return await ExportService(session).export_html_zip(start, end, report=report)

        return start_export_job(
            background_tasks, "export-html-zip", "lifelogr-export-html.zip", _build,
            session_factory=async_session,
        )

    staged = await ExportService(db).export_html_zip(start, end)
    return _staged_file_response(staged, "lifelogr-export-html.zip", "application/zip")


@router.get("/export/diarium")
async def export_diarium(
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries + notes + media as the native LifeLogr archive ZIP.

    Full-fidelity, self-contained: ``lifelogr.json`` (entries with media and
    events, notes with folders/pages/attachments) plus every referenced media
    file under ``media/``. Re-imports via ``/import/file`` — media rows are
    recreated and body URLs are rewritten to the new ids. ``as_job=true``
    returns ``{job_id}``; download from ``GET /api/v1/jobs/{job_id}/result``.
    """
    if as_job:
        from app.core.database import async_session

        async def _build(report: ProgressReporter, session: AsyncSession) -> Path:
            entries = await _export_entries(session, start_date, end_date)
            notes = await _load_archive_notes(session)
            return await asyncio.to_thread(build_archive, entries, notes, report)

        return start_export_job(
            background_tasks, "export-archive", "lifelogr-archive.zip", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    notes = await _load_archive_notes(db)
    staged = await asyncio.to_thread(build_archive, entries, notes)
    return _staged_file_response(staged, "lifelogr-archive.zip", "application/zip")


@router.get("/export/json")
async def export_json(
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
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

        async def _build(report: ProgressReporter, session: AsyncSession) -> Path:
            entries = await _export_entries(session, start_date, end_date)
            return await build_diarium_database(entries, report=report)

        return start_export_job(
            background_tasks, "export-diary", "lifelogr-export.diary", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date)
    # build_diarium_database offloads its SQLite build to a worker thread.
    staged = await build_diarium_database(entries)
    return _staged_file_response(staged, "lifelogr-export.diary", "application/octet-stream")


@router.get("/export/dayone-zip")
async def export_dayone_zip(
    background_tasks: BackgroundTasks,
    start_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    scope: str = Query(
        "new",
        description=(
            "new (default): only entries Diarium has not received — no source "
            "identity, and no entry on a day Diarium already has. all: everything."
        ),
    ),
    as_job: bool = Query(False, description="Build as a polled job; returns {job_id}"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as a Day One JSON ZIP — Diarium's attachment-capable import.

    Diarium reads this via Settings → Migrate from other app → Day One, which
    **adds** entries it has not seen and skips date/times that already exist, so
    this is the push half of a file-based sync. Media are written as
    ``photos/<md5>.<ext>`` — the naming Diarium resolves attachments by.
    Encrypted entries are skipped (their body is ciphertext) and counted in
    ``Journal.json``'s metadata. ``as_job=true`` returns ``{job_id}``; download
    from ``GET /api/v1/jobs/{job_id}/result``.
    """
    if scope not in ("new", "all"):
        raise HTTPException(
            status_code=400, detail=f"Unknown scope {scope!r}; expected 'new' or 'all'."
        )
    only_new = scope == "new"
    if as_job:
        from app.core.database import async_session

        async def _build(report: ProgressReporter, session: AsyncSession) -> Path:
            entries = await _export_entries(session, start_date, end_date, only_new=only_new)
            return await build_dayone_zip(entries, report=report)

        return start_export_job(
            background_tasks, "export-dayone", "lifelogr-dayone.zip", _build,
            session_factory=async_session,
        )

    entries = await _export_entries(db, start_date, end_date, only_new=only_new)
    staged = await build_dayone_zip(entries)
    return _staged_file_response(staged, "lifelogr-dayone.zip", "application/zip")


@router.post("/backfill-titles", response_model=dict)
async def backfill_titles(
    dry_run: bool = Query(
        True, description="Report what would change without writing (default)."
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Derive titles for untitled entries from their first meaningful line.

    Mirrors the editor's auto-title rule (`services/title_service.py`). Dry run
    by default — the UI shows the count and samples first. A backfilled title
    also refreshes `sync_hash`, otherwise the next Diarium pull would treat our
    own title as a local edit and report a conflict forever.
    """
    from sqlalchemy import update

    from app.services.title_service import derive_title

    rows = (
        await db.execute(
            select(
                Entry.id,
                Entry.body,
                Entry.mood,
                Entry.latitude,
                Entry.longitude,
                Entry.sync_hash,
            )
            .where(
                ~Entry.is_deleted,
                sa_func.trim(sa_func.coalesce(Entry.title, "")) == "",
            )
            .order_by(Entry.entry_date)
            .limit(5000)
        )
    ).all()

    candidates: list[tuple[int, str, str, Any, Any, Any, Any]] = []
    for entry_id, body, mood, latitude, longitude, sync_hash in rows:
        derived = derive_title(body)
        if derived:
            candidates.append(
                (entry_id, derived, body, mood, latitude, longitude, sync_hash)
            )

    if dry_run:
        return {
            "dry_run": True,
            "candidates": len(candidates),
            "updated": 0,
            "samples": [
                {"id": entry_id, "title": derived}
                for entry_id, derived, *_ in candidates[:5]
            ],
        }

    updated = 0
    for entry_id, derived, body, mood, latitude, longitude, sync_hash in candidates:
        values: dict[str, Any] = {"title": derived}
        if sync_hash is not None:
            values["sync_hash"] = _entry_text_hash(
                derived, body, mood, latitude, longitude
            )
        await db.execute(update(Entry).where(Entry.id == entry_id).values(**values))
        updated += 1
    await db.commit()
    logger.info("Backfilled %d entry titles", updated)
    return {
        "dry_run": False,
        "candidates": len(candidates),
        "updated": updated,
        "samples": [
            {"id": entry_id, "title": derived}
            for entry_id, derived, *_ in candidates[:5]
        ],
    }


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
    """Soft-delete an entry (restorable trash — media are kept)."""
    svc = EntryService(db)
    await svc.soft_delete(entry_id)


@router.delete("/{entry_id}/purge", status_code=204)
async def purge_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Permanently delete an entry and its media files (no recovery)."""
    svc = EntryService(db)
    await svc.purge(entry_id)


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
    """Spool an upload to a temp file, aborting past ``max_bytes`` with 413."""

    def _too_large(limit: int) -> Exception:
        return HTTPException(
            status_code=413,
            detail=f"Import file exceeds the {limit}-byte limit.",
        )

    suffix = Path(file.filename or "import").suffix[:16] or ".bin"
    path, _ = await spool_upload(file, max_bytes, suffix=suffix, on_overflow=_too_large)
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
    ``{filename, media_type, data | load, caption?, is_inline?, ref?}``
    (``data`` bytes or a ``load`` callable returning them). Returns
    ``{ref: new_id}`` for body-URL remapping. Bytes go through the same
    signature and size checks as uploads: an import path must never become a
    way to smuggle blocked file types past MediaService.
    """
    ref_map: dict[int, int] = {}
    for item in media_items:
        data = item.get("data") or b""
        if not data:
            # .diary imports carry a lazy ``load`` instead of the bytes, so the
            # backup's media is pulled one blob at a time, not held in RAM.
            load = item.get("load")
            data = load() if callable(load) else b""
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
            check_signature(data[:64], filename)
        except MediaSizeError as e:
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
    mode: str = Query(
        "merge",
        description=(
            "merge (default): match entries already imported — by source id "
            "(Diarium DiaryEntryId) first, else date + body — and attach any "
            "missing media/events. append: always insert new rows."
        ),
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
    if mode not in _IMPORT_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown import mode {mode!r}; expected one of {_IMPORT_MODES}.",
        )
    # append is the old always-insert behaviour and overrides dedup entirely;
    # merge needs the dedup index, so skip_duplicates=false degrades to append.
    if mode == "append":
        skip_duplicates = False

    filename = file.filename or ""

    entries_data: list[dict[str, Any]] = []
    archive_notes: list[dict[str, Any]] = []

    upload_path = await _spool_upload(file, settings.MAX_IMPORT_SIZE_BYTES)
    # .diary media blobs are read lazily from the spooled file during the
    # insert loop, so it is unlinked only after the import finishes (see the
    # .diary branch); every other format is fully parsed below and can go now.
    is_diary = filename.endswith(".diary")
    try:
        if is_diary:
            # Diarium .diary SQLite database — parsing lives in the importers
            # service. The path (not the bytes) is handed over: reading a
            # multi-gigabyte backup into memory crashed the process.
            entries_data.extend(parse_diarium_sqlite(upload_path))
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
                            events_items = [
                                {
                                    "kind": ev.get("kind"),
                                    "content": ev.get("content"),
                                    "label": ev.get("label"),
                                }
                                for ev in item.get("events", [])
                            ]
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
                                    "events": events_items,
                                }
                            )
                        # v2 archives carry notes inline (v1 archives simply
                        # lack the key — same import path either way).
                        for item in doc.get("notes", []):
                            for m in item.get("media", []):
                                member = m.get("path", "")
                                m["data"] = (
                                    _read_member(z, member)
                                    if member in media_names
                                    else b""
                                )
                            archive_notes.append(item)
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
        if not is_diary:
            upload_path.unlink(missing_ok=True)

    if not as_job:
        try:
            result = await _run_entry_import(db, entries_data, skip_duplicates, mode=mode)
            if archive_notes:
                await _run_note_archive_import(db, archive_notes)
                await db.commit()
            return result
        finally:
            if is_diary:
                upload_path.unlink(missing_ok=True)

    def _runner(job_report: ProgressReporter) -> Awaitable[str]:
        async def _run() -> str:
            from app.core.database import async_session

            try:
                async with async_session() as session:
                    result = await _run_entry_import(
                        session, entries_data, skip_duplicates, job_report, mode=mode
                    )
                    if archive_notes:
                        await _run_note_archive_import(session, archive_notes)
                        await session.commit()
                    detail = (
                        f"Imported {result['imported']}, updated {result['updated']}, "
                        f"skipped {result['skipped']}, media {result['media_backfilled']}"
                    )
                    if result["conflicts"]:
                        detail += f", conflicts {result['conflicts']}"
                    return detail
            finally:
                if is_diary:
                    upload_path.unlink(missing_ok=True)

        return _run()

    return _start_data_job(background_tasks, "import-entries", _runner)


async def _run_entry_import(
    db: AsyncSession,
    entries_data: list[dict[str, Any]],
    skip_duplicates: bool,
    report: ProgressReporter = noop_reporter,
    *,
    mode: str = "merge",
) -> dict[str, Any]:
    """Insert or reconcile parsed entries: dedup, tags/trackers, media, events.

    Shared by /import/file's sync and job paths (and shaped for reuse); *report*
    phases: insert (done/total per parsed record).

    In ``merge`` mode a record is matched to an existing row by the source's own
    id (Diarium ``DiaryEntryId``) first, then by ``date + body[:1000] + mood``
    for rows imported before identity tracking existed. Matched rows get their
    missing media/events/tags attached — media compared by content hash, so a
    partial loss is repaired, not just a total one — and their text is updated
    only when the local copy is provably untouched since the previous import
    (``sync_hash``). Anything ambiguous becomes a conflict: local text wins and
    the pull is reported, never silently overwritten.
    """
    import hashlib
    from datetime import date as date_type

    from sqlalchemy import func as sa_func

    from app.models.tag import Tag

    merge = mode == "merge" and skip_duplicates
    svc = EntryService(db)
    # Pre-load all existing tags to avoid N+1 lookups
    existing_tags_result = await db.execute(select(Tag))
    tag_cache: dict[str, Tag] = {t.name: t for t in existing_tags_result.scalars().all()}

    # Duplicate detection: (entry_date, sha256(body[:1000] + mood)) → entry id.
    # Only the first 1000 body characters are pulled from SQL (``substr``), so
    # the full body of every entry is never materialised just to fingerprint it.
    # The mood suffix keeps same-day mood-only check-ins distinct.
    existing_sigs: dict[tuple[str, str], int] = {}
    # Source identity → entry id. Deliberately includes soft-deleted rows: the
    # unique index still owns that id, and re-importing must not resurrect a
    # row the user deleted.
    external_index: dict[str, int] = {}
    if skip_duplicates:
        _rows = await db.execute(
            select(
                Entry.id,
                Entry.entry_date,
                sa_func.substr(Entry.body, 1, 1000),
                Entry.mood,
            ).where(~Entry.is_deleted)
        )
        for _id, _ed, _prefix, _mood in _rows.all():
            existing_sigs[
                (
                    str(_ed),
                    hashlib.sha256(
                        ((_prefix or "") + "\x00" + (_mood or "")).encode()
                    ).hexdigest(),
                )
            ] = _id

        incoming_external_ids = sorted(
            {str(e["external_id"]) for e in entries_data if e.get("external_id")}
        )
        for start in range(0, len(incoming_external_ids), 400):
            chunk = incoming_external_ids[start : start + 400]
            _ext_rows = await db.execute(
                select(Entry.id, Entry.external_id).where(Entry.external_id.in_(chunk))
            )
            for _id, _ext in _ext_rows.all():
                if _ext:
                    external_index[str(_ext)] = _id

    imported = 0
    updated = 0
    backfilled = 0
    conflicts = 0
    skipped = 0
    skip_reasons: list[ImportSkipReason] = []
    since_commit = 0
    # Entry id → digest multiset of its media blobs, built lazily so only
    # entries that already own media pay the file reads.
    media_hashes: dict[int, Counter[str]] = {}
    # Enrichment is queued only for rows that are already committed — the
    # workers use their own sessions and can't see uncommitted rows.
    to_enrich: list[tuple[int, str | None, str]] = []

    async def _commit_batch() -> None:
        """Commit the in-flight chunk, then release its enrichment jobs."""
        if not imported and not updated and not backfilled and not to_enrich:
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
        # Diarium entries), a mood (Daylio mood-only check-ins), or a title
        # (Diarium anniversary/event entries); only truly empty records are
        # skipped.
        if not entry.get("entry_date") or (
            not entry.get("body")
            and not entry.get("media")
            and not entry.get("mood")
            and not entry.get("title")
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

            # Source identity wins over the (lossy) text fingerprint. The
            # fingerprint is only a fallback for rows imported before identity
            # tracking existed, so the first merge after upgrading adopts them
            # instead of duplicating them.
            ext_id = str(entry["external_id"]) if merge and entry.get("external_id") else None
            matched_row: Entry | None = None
            if ext_id and ext_id in external_index:
                matched_row = await db.get(Entry, external_index[ext_id])
            elif merge and sig in existing_sigs:
                candidate = await db.get(Entry, existing_sigs[sig])
                # Same text but a different source entry: keep both rather than
                # collapsing two distinct Diarium entries into one.
                if candidate is not None and (
                    not ext_id or not candidate.external_id or candidate.external_id == ext_id
                ):
                    matched_row = candidate

            if matched_row is not None:
                existing_sigs[sig] = matched_row.id
                if ext_id:
                    external_index[ext_id] = matched_row.id
                if matched_row.is_deleted:
                    skipped += 1
                    skip_reasons = _record_skip(
                        skip_reasons,
                        idx,
                        str(ed),
                        entry.get("title"),
                        "matches an entry deleted in LifeLogr",
                    )
                else:
                    outcome = await _merge_existing_entry(
                        db, matched_row, entry, tag_cache, media_hashes
                    )
                    backfilled += outcome["media"]
                    conflicts += int(outcome["conflict"])
                    if outcome["updated"]:
                        updated += 1
                        if not matched_row.is_encrypted:
                            to_enrich.append(
                                (matched_row.id, matched_row.title, matched_row.body or "")
                            )
                    else:
                        skipped += 1
                        skip_reasons = _record_skip(
                            skip_reasons,
                            idx,
                            str(ed),
                            entry.get("title"),
                            (
                                "duplicate of existing entry (conflict: kept the local edit)"
                                if outcome["conflict"]
                                else "duplicate of existing entry (merged)"
                            ),
                        )
                report("insert", idx + 1, total)
                since_commit += 1
                if since_commit >= _IMPORT_COMMIT_CHUNK:
                    await _commit_batch()
                    since_commit = 0
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
            if merge:
                created.external_source = entry.get("external_source") or (
                    "diarium" if ext_id else None
                )
                created.external_id = ext_id
                created.external_updated_at = _coerce_datetime(
                    entry.get("external_updated_at")
                )
                created.sync_hash = _entry_text_hash(
                    created.title, created.body, created.mood, created.latitude, created.longitude
                )
                if ext_id:
                    external_index[ext_id] = created.id
            if not created.is_encrypted:
                to_enrich.append((created.id, created.title, created.body))
            existing_sigs[sig] = created.id
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
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "media_backfilled": backfilled,
        "conflicts": conflicts,
        "skip_reasons": skip_reasons,
    }


def _entry_text_hash(
    title: str | None,
    body: str | None,
    mood: str | None,
    latitude: float | None,
    longitude: float | None,
) -> str:
    """Fingerprint the fields a source pull can change on an entry.

    Tags and media are reconciled additively, so they are deliberately excluded:
    a tag-only difference must not look like a text conflict. ``0`` means
    "unset" in Diarium's schema, so it hashes as empty.
    """
    import hashlib

    lat = f"{float(latitude):.6f}" if latitude else ""
    lon = f"{float(longitude):.6f}" if longitude else ""
    payload = "\x00".join([(title or "").strip(), body or "", mood or "", lat, lon])
    return hashlib.sha256(payload.encode()).hexdigest()


def _coerce_datetime(value: Any) -> datetime | None:
    """Accept a datetime (SQLite source) or an ISO string (JSON source)."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _entry_media_hashes(db: AsyncSession, entry_id: int) -> Counter[str]:
    """Content digests of an entry's stored media, for attachment-level dedupe.

    Files are hashed from disk because Diarium's blob identity (``DiaryMediaId``)
    does not survive a re-export; the bytes do. A row whose file vanished still
    counts as absent, so a later pull can restore it. Counted (not a set) so two
    deliberately identical photos in one entry survive a re-import.
    """
    import hashlib

    paths = (
        (await db.execute(select(Media.storage_path).where(Media.entry_id == entry_id)))
        .scalars()
        .all()
    )
    digests: Counter[str] = Counter()
    for storage_path in paths:
        try:
            digests[
                hashlib.sha256(
                    (Path(settings.MEDIA_DIR) / storage_path).read_bytes()
                ).hexdigest()
            ] += 1
        except OSError:
            logger.warning("Imported media missing on disk, cannot fingerprint: %s", storage_path)
    return digests


async def _merge_existing_entry(
    db: AsyncSession,
    row: Entry,
    entry: dict[str, Any],
    tag_cache: dict[str, Any],
    media_hashes: dict[int, Counter[str]],
) -> dict[str, Any]:
    """Fold one source record into an already-imported entry (idempotent).

    Adds only what is missing — media by content hash (a partially lost entry is
    repaired, not just a totally empty one), events by (kind, content, label),
    tags/trackers additively — and updates the text only when ``sync_hash``
    proves the local copy is untouched since the previous import. Otherwise the
    local text wins and the caller reports a conflict.
    """
    import hashlib

    from app.models.entry_event import EntryEvent
    from app.models.tag import Tag

    attached = 0
    media_items = entry.get("media") or []
    if media_items:
        known = media_hashes.get(row.id)
        if known is None:
            known = await _entry_media_hashes(db, row.id)
            media_hashes[row.id] = known
        fresh: list[dict[str, Any]] = []
        for item in media_items:
            data = item.get("data") or b""
            if not data:
                load = item.get("load")
                data = load() if callable(load) else b""
            if not data:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if known[digest] > 0:
                # One stored copy already matches these bytes; consume it so a
                # second identical attachment in the same entry is still added.
                known[digest] -= 1
                continue
            fresh.append({**item, "data": data, "load": None})
        if fresh:
            await _attach_imported_media(db, row, fresh)
            attached = len(fresh)

    events = entry.get("events") or []
    if events:
        seen_events = {
            (kind, content, label)
            for kind, content, label in (
                await db.execute(
                    select(EntryEvent.kind, EntryEvent.content, EntryEvent.label).where(
                        EntryEvent.entry_id == row.id
                    )
                )
            ).all()
        }
        fresh_events: list[dict[str, Any]] = []
        for ev in events:
            content = str(ev.get("content") or "").strip()
            if not content:
                continue
            key = (
                str(ev.get("kind") or "unknown:?"),
                content,
                str(ev["label"]) if ev.get("label") else None,
            )
            if key in seen_events:
                continue
            seen_events.add(key)
            fresh_events.append(ev)
        if fresh_events:
            await _attach_imported_events(db, row, fresh_events)

    # Tags and tracker readings are additive: a pull must never drop a
    # LifeLogr-side #hashtag. Only fill in what the entry is missing.
    existing_tags = {
        tag_id: value
        for tag_id, value in (
            await db.execute(
                select(EntryTag.tag_id, EntryTag.tracking_value).where(
                    EntryTag.entry_id == row.id
                )
            )
        ).all()
    }
    assigned = set(existing_tags)
    for tr in entry.get("trackers") or []:
        name = (tr.get("name") or "").strip()
        if not name:
            continue
        tag = tag_cache.get(name)
        if tag is None:
            tag = Tag(name=name, is_tracker=True)
            tag_cache[name] = tag
            db.add(tag)
            await db.flush()
        elif not tag.is_tracker:
            tag.is_tracker = True
        value = tr.get("value")
        if tag.id not in assigned:
            db.add(EntryTag(entry_id=row.id, tag_id=tag.id, tracking_value=None))
            assigned.add(tag.id)
            existing_tags[tag.id] = None
        if value is not None and existing_tags.get(tag.id) != str(value):
            from sqlalchemy import update as sa_update

            await db.execute(
                sa_update(EntryTag)
                .where(EntryTag.entry_id == row.id, EntryTag.tag_id == tag.id)
                .values(tracking_value=str(value)[:500])
            )
            existing_tags[tag.id] = str(value)
    for name in entry.get("tags") or []:
        if not name:
            continue
        tag = tag_cache.get(name)
        if tag is None:
            tag = Tag(name=name)
            tag_cache[name] = tag
            db.add(tag)
            await db.flush()
        if tag.id not in assigned:
            db.add(EntryTag(entry_id=row.id, tag_id=tag.id))
            assigned.add(tag.id)

    incoming_hash = _entry_text_hash(
        entry.get("title"),
        entry.get("body"),
        entry.get("mood"),
        entry.get("latitude"),
        entry.get("longitude"),
    )
    current_hash = _entry_text_hash(row.title, row.body, row.mood, row.latitude, row.longitude)
    updated = False
    conflict = False

    if row.external_id is None and entry.get("external_id"):
        row.external_source = entry.get("external_source") or "diarium"
        row.external_id = str(entry["external_id"])

    if row.sync_hash is None:
        # Pre-identity row (the 1393 imported before identity tracking) or the
        # first pull for this row: adopt it and record the source content as
        # the baseline WITHOUT touching local text. Fields the older import
        # never captured (geo, mood, title) are filled only when missing, so
        # they neither count as a text conflict nor overwrite anything.
        if row.title is None and entry.get("title"):
            row.title = entry.get("title")
        if row.mood is None and entry.get("mood"):
            row.mood = entry.get("mood")
        if row.latitude is None and entry.get("latitude"):
            row.latitude = entry.get("latitude")
        if row.longitude is None and entry.get("longitude"):
            row.longitude = entry.get("longitude")
        row.sync_hash = incoming_hash
    elif row.sync_hash == current_hash:
        if incoming_hash != current_hash:
            row.title = entry.get("title")
            row.body = entry.get("body") or ""
            row.mood = entry.get("mood")
            row.latitude = entry.get("latitude")
            row.longitude = entry.get("longitude")
            updated = True
        row.sync_hash = incoming_hash
    else:
        conflict = True

    source_updated_at = _coerce_datetime(entry.get("external_updated_at"))
    if source_updated_at is not None:
        row.external_updated_at = source_updated_at

    await db.flush()
    return {"media": attached, "updated": updated, "conflict": conflict}
