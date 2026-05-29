"""Media attachment route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.media import MediaResponse
from app.services.media_service import MediaService

router = APIRouter(prefix="/api/v1/media", tags=["media"])


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


@router.get("/{media_id}", response_model=MediaResponse)
async def get_media(media_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get media metadata."""
    svc = MediaService(db)
    return await svc.get(media_id)


@router.get("/{media_id}/file")
async def download_media(media_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Download the raw media file."""
    svc = MediaService(db)
    data, content_type, filename = await svc.get_file(media_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(media_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a media attachment and its file."""
    svc = MediaService(db)
    await svc.delete(media_id)


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


@router.get("/entry/{entry_id}", response_model=list[MediaResponse])
async def list_entry_media(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all media attachments for an entry."""
    svc = MediaService(db)
    return await svc.list_for_entry(entry_id)
