"""Media attachment route handlers."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.media import MediaResponse, MediaTimelineItem, MediaTimelineResponse
from app.services.media_service import MediaService

router = APIRouter(prefix="/api/v1/media", tags=["media"])
logger = logging.getLogger(__name__)


@router.post("", response_model=MediaResponse, status_code=201)
async def upload_media(
    entry_id: int = Form(...),
    caption: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload a media file and attach it to an entry."""
    svc = MediaService(db)
    file_data = await file.read()
    return await svc.upload(
        entry_id,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        file_data,
        caption,
    )


# ── Batch upload & listing ─────────────────────────────────────────────────────


@router.post("/batch", response_model=list[MediaResponse], status_code=201)
async def batch_upload(
    entry_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload multiple media files and attach them to an entry."""
    svc = MediaService(db)
    results = []
    for f in files:
        data = await f.read()
        media = await svc.upload(
            entry_id, f.filename or "upload", f.content_type or "application/octet-stream", data
        )
        results.append(media)
    return results


@router.get("/all", response_model=MediaTimelineResponse)
async def list_all_media(
    offset: int = 0,
    limit: int = 50,
    media_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all media across entries, grouped-ready with entry context."""
    svc = MediaService(db)
    results, total = await svc.list_all(offset=offset, limit=limit, media_type=media_type)
    timeline_items = [
        MediaTimelineItem(
            id=m.id,
            entry_id=m.entry_id,
            filename=m.filename,
            media_type=m.media_type,
            file_size=m.file_size,
            caption=m.caption,
            created_at=m.created_at,
            entry_date=entry_date,
            entry_title=entry_title,
        )
        for m, entry_date, entry_title in results
    ]
    return MediaTimelineResponse(items=timeline_items, total=total)


@router.get("/entry/{entry_id}", response_model=list[MediaResponse])
async def list_entry_media(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all media attachments for an entry."""
    svc = MediaService(db)
    return await svc.list_for_entry(entry_id)


# ── Single media operations (parametrized paths last) ──────────────────────────


@router.get("/{media_id}", response_model=MediaResponse)
async def get_media(media_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get media metadata."""
    svc = MediaService(db)
    return await svc.get(media_id)


@router.post("/{media_id}/ocr")
async def ocr_media(media_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Extract text from an image attachment via OCR (tesseract/pytesseract)."""
    svc = MediaService(db)
    media = await svc.get(media_id)
    if not (media.media_type == "image" or media.media_type.startswith("image/")):
        raise HTTPException(status_code=400, detail="OCR is only available for images.")

    file_data, _content_type, _filename = await svc.get_file(media.id)
    try:
        import pytesseract  # type: ignore[import-untyped]
        from PIL import Image
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=f"OCR unavailable: {exc}") from exc

    try:
        text = await asyncio.to_thread(
            pytesseract.image_to_string, Image.open(io.BytesIO(file_data))
        )
    except Exception as exc:
        # Most common cause: the `tesseract` system binary isn't installed.
        logger.error("OCR failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="OCR failed — is the `tesseract` binary installed? "
            "Run System Setup (Settings → Features) or: sudo apt install tesseract-ocr",
        ) from exc
    return {"text": text.strip()}


@router.get("/{media_id}/file")
async def download_media(media_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Stream the raw media file with HTTP range support.

    ``FileResponse`` serves from disk and honours ``Range`` requests, which is
    required for <video>/<audio> playback and seeking. Returning the whole blob
    as a single ``Response(content=data)`` breaks media playback.
    """
    svc = MediaService(db)
    path, content_type, filename = await svc.get_file_path(media_id)
    return FileResponse(
        path=str(path),
        media_type=content_type,
        filename=filename,
        # `inline` lets the browser render/play rather than force-download.
        content_disposition_type="inline",
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(media_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a media attachment and its file."""
    svc = MediaService(db)
    await svc.delete(media_id)
