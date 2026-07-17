"""Notes route handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.note import Note
from app.schemas.note import (
    NoteCreate,
    NoteFolderCreate,
    NoteFolderResponse,
    NoteFolderUpdate,
    NoteListResponse,
    NotePageCreate,
    NotePageReorder,
    NotePageResponse,
    NotePageUpdate,
    NoteResponse,
    NoteUpdate,
)
from app.schemas.note_media import NoteMediaFromPath, NoteMediaResponse
from app.schemas.tag import TagBrief
from app.services.note_media_service import NoteMediaService
from app.services.note_service import NoteService
from app.services.ocr_service import ocr_image_bytes

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])
logger = logging.getLogger(__name__)


def _to_response(note: Note) -> NoteResponse:
    """Convert a Note ORM object to NoteResponse schema."""
    return NoteResponse(
        id=note.id,
        folder_id=note.folder_id,
        title=note.title,
        body=note.body,
        is_pinned=note.is_pinned,
        color=note.color,
        is_encrypted=note.is_encrypted,
        encrypted_at=note.encrypted_at,
        tags=[TagBrief(id=a.tag.id, name=a.tag.name) for a in note.tag_associations if a.tag],
        pages=[NotePageResponse.model_validate(p) for p in note.pages],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


class _PinBody(BaseModel):
    is_pinned: bool


class _WebClipBody(BaseModel):
    url: HttpUrl


@router.post("", response_model=NoteResponse, status_code=201)
async def create_note(data: NoteCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a new note."""
    svc = NoteService(db)
    return _to_response(await svc.create(data))


@router.get("", response_model=NoteListResponse)
async def list_notes(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    folder_id: int | None = Query(None),
    tag_ids: str | None = Query(None),
    is_pinned: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List notes with optional filters and pagination (pinned-first)."""
    svc = NoteService(db)
    parsed_tag_ids = [int(t) for t in tag_ids.split(",")] if tag_ids else None
    notes, total = await svc.list_notes(offset, limit, folder_id, parsed_tag_ids, is_pinned)
    return NoteListResponse(
        items=[_to_response(n) for n in notes], total=total, offset=offset, limit=limit
    )


@router.get("/search", response_model=NoteListResponse)
async def search_notes(
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Full-text search on notes (notes_fts, ILIKE fallback)."""
    svc = NoteService(db)
    notes, total = await svc.search(q, offset, limit)
    return NoteListResponse(
        items=[_to_response(n) for n in notes], total=total, offset=offset, limit=limit
    )


@router.post("/web-clip")
async def web_clip(data: _WebClipBody) -> dict[str, str]:
    """Clip a web page to markdown.

    Fallback for the desktop web-page image capture: the Tauri shell captures
    the page as a picture (then OCRs it); this text path is used when capture
    is unavailable (web build) or fails. SSRF-hardened (see web_clip_service).
    """
    from app.services.web_clip_service import extract_markdown_from_url

    return {"markdown": await extract_markdown_from_url(str(data.url))}


# ── Sub-pages (EPIM-style page tabs) ────────────────────────────────────────


@router.post("/{note_id}/pages", response_model=NotePageResponse, status_code=201)
async def create_page(
    note_id: int, data: NotePageCreate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Append a new page tab to a note."""
    svc = NoteService(db)
    return await svc.create_page(note_id, data)


@router.post("/{note_id}/pages/reorder")
async def reorder_pages(
    note_id: int, data: NotePageReorder, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    """Re-set sort_order for the given pages (scoped to note_id)."""
    svc = NoteService(db)
    await svc.reorder_pages(note_id, data.items)
    return {"reordered": len(data.items)}


@router.patch("/{note_id}/pages/{page_id}", response_model=NotePageResponse)
async def update_page(
    note_id: int, page_id: int, data: NotePageUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = NoteService(db)
    return await svc.update_page(note_id, page_id, data)


@router.delete("/{note_id}/pages/{page_id}", status_code=204)
async def delete_page(note_id: int, page_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = NoteService(db)
    await svc.delete_page(note_id, page_id)


@router.get("/folders", response_model=list[NoteFolderResponse])
async def list_folders(db: AsyncSession = Depends(get_db)) -> Any:
    """List non-deleted folders with their live note counts."""
    svc = NoteService(db)
    pairs = await svc.list_folders()
    return [
        NoteFolderResponse(
            id=folder.id,
            name=folder.name,
            parent_id=folder.parent_id,
            color=folder.color,
            sort_order=folder.sort_order,
            note_count=count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )
        for folder, count in pairs
    ]


@router.post("/folders", response_model=NoteFolderResponse, status_code=201)
async def create_folder(data: NoteFolderCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a note folder."""
    svc = NoteService(db)
    folder = await svc.create_folder(data)
    return NoteFolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        color=folder.color,
        sort_order=folder.sort_order,
        note_count=0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.patch("/folders/{folder_id}", response_model=NoteFolderResponse)
async def update_folder(
    folder_id: int, data: NoteFolderUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Update a note folder."""
    svc = NoteService(db)
    folder = await svc.update_folder(folder_id, data)
    return NoteFolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        color=folder.color,
        sort_order=folder.sort_order,
        note_count=0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete a note folder."""
    svc = NoteService(db)
    await svc.soft_delete_folder(folder_id)


# ── Note media (drag-and-drop / paste image embedding) ──


@router.post("/{note_id}/media", response_model=NoteMediaResponse, status_code=201)
async def upload_note_media(
    note_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload a media file attached to a note (used for inline image embedding)."""
    svc = NoteMediaService(db)
    data = await file.read()
    return await svc.upload(
        note_id,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        data,
        caption,
    )


@router.post("/{note_id}/media/from-path", response_model=NoteMediaResponse, status_code=201)
async def upload_note_media_from_path(
    note_id: int, data: NoteMediaFromPath, db: AsyncSession = Depends(get_db)
) -> Any:
    """Import a local file by absolute path as note media.

    Used by the Tauri native drag-drop handler, which receives a file path
    (WebKitGTK doesn't deliver HTML5 file drops to the webview).
    """
    svc = NoteMediaService(db)
    return await svc.upload_from_path(note_id, data.path, data.caption)


@router.get("/{note_id}/media", response_model=list[NoteMediaResponse])
async def list_note_media(note_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all media attachments for a note."""
    svc = NoteMediaService(db)
    return await svc.list_for_note(note_id)


@router.get("/{note_id}/media/{media_id}/file")
async def download_note_media(
    note_id: int, media_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    """Stream a note media file (inline, with HTTP range support)."""
    svc = NoteMediaService(db)
    path, content_type, filename = await svc.get_file_path(media_id, note_id)
    return FileResponse(
        path=str(path),
        media_type=content_type,
        filename=filename,
        content_disposition_type="inline",
    )


@router.delete("/{note_id}/media/{media_id}", status_code=204)
async def delete_note_media(
    note_id: int, media_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    """Delete a note media attachment and its file."""
    svc = NoteMediaService(db)
    await svc.delete(media_id, note_id)


@router.post("/{note_id}/media/{media_id}/ocr")
async def ocr_note_media(
    note_id: int, media_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Extract text from a note image attachment via OCR (tesseract/pytesseract).

    Returns only the recognized text. The frontend inserts it into the note
    body; the autosave PATCH then makes it searchable (the ``notes_fts``
    AFTER-UPDATE trigger reindexes ``notes.body``).
    """
    svc = NoteMediaService(db)
    path, content_type, _filename = await svc.get_file_path(media_id, note_id)
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="OCR is only available for images.")

    try:
        text = await asyncio.to_thread(ocr_image_bytes, path.read_bytes())
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=f"OCR unavailable: {exc}") from exc
    except Exception as exc:
        # Most common cause: the `tesseract` system binary isn't installed.
        logger.error("Note OCR failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="OCR failed — is the `tesseract` binary installed? "
            "Run System Setup (Settings → Features) or: sudo apt install tesseract-ocr",
        ) from exc
    return {"text": text.strip()}


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a single note by ID."""
    svc = NoteService(db)
    return _to_response(await svc.get(note_id))


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, data: NoteUpdate, db: AsyncSession = Depends(get_db)) -> Any:
    """Update an existing note."""
    svc = NoteService(db)
    return _to_response(await svc.update(note_id, data))


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete a note."""
    svc = NoteService(db)
    await svc.soft_delete(note_id)


@router.post("/{note_id}/restore", response_model=NoteResponse)
async def restore_note(note_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Restore a previously soft-deleted note (re-indexes it in notes_fts)."""
    svc = NoteService(db)
    return _to_response(await svc.restore(note_id))


@router.patch("/{note_id}/pin", response_model=NoteResponse)
async def pin_note(note_id: int, body: _PinBody, db: AsyncSession = Depends(get_db)) -> Any:
    """Set the pinned state of a note."""
    svc = NoteService(db)
    return _to_response(await svc.set_pinned(note_id, body.is_pinned))
