"""Video note route handlers."""

from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.video_note import VideoNoteListResponse, VideoNoteResponse
from app.services.media_service import spool_upload
from app.services.video_service import VideoService

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


@router.post("", response_model=VideoNoteResponse, status_code=201)
async def upload_video(
    entry_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload a video note attached to an entry."""
    svc = VideoService(db)
    # Spool to disk with incremental size enforcement instead of materialising
    # the whole clip in RAM before the 25 MB check runs.
    spool, _size = await spool_upload(file, settings.MAX_MEDIA_SIZE_BYTES)
    try:
        return await svc.upload_file(
            entry_id, file.filename or "video.mp4", file.content_type or "video/mp4", spool
        )
    finally:
        spool.unlink(missing_ok=True)


@router.get("/entry/{entry_id}", response_model=VideoNoteListResponse)
async def list_entry_videos(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all video notes for an entry."""
    svc = VideoService(db)
    items = await svc.list_for_entry(entry_id)
    return {"items": items, "total": len(items)}


@router.get("/{video_id}", response_model=VideoNoteResponse)
async def get_video(video_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get video note metadata."""
    svc = VideoService(db)
    return await svc.get(video_id)


@router.get("/{video_id}/file")
async def download_video(video_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Stream the raw video file with HTTP range support.

    ``FileResponse`` serves from disk and honours ``Range`` requests, which is
    required for <video> playback and seeking. Returning the whole clip as a
    single ``Response(content=data)`` loads it into RAM *and* breaks seeking —
    the same bug the media download endpoint already fixed.
    """
    svc = VideoService(db)
    note = await svc.get(video_id)
    path = svc.get_file_path(note)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file missing on disk")
    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=note.filename,
        # `inline` lets the browser play rather than force-download.
        content_disposition_type="inline",
    )


@router.delete("/{video_id}", status_code=204)
async def delete_video(video_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a video note and its file."""
    svc = VideoService(db)
    await svc.delete(video_id)
