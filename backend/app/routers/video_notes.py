"""Video note route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.video_note import VideoNoteListResponse, VideoNoteResponse
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
    data = await file.read()
    note = await svc.upload(
        entry_id, file.filename or "video.mp4", file.content_type or "video/mp4", data
    )
    return note


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
async def download_video(video_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Download the raw video file."""
    svc = VideoService(db)
    note = await svc.get(video_id)
    path = svc.get_file_path(note)
    return Response(
        content=path.read_bytes(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'inline; filename="{note.filename}"'},
    )


@router.delete("/{video_id}", status_code=204)
async def delete_video(video_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a video note and its file."""
    svc = VideoService(db)
    await svc.delete(video_id)
