"""Voice recording route handlers."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import VoiceRecording
from app.schemas.recording import VoiceRecordingResponse
from app.services.recording_service import VoiceRecordingService

router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


@router.post("", response_model=VoiceRecordingResponse, status_code=201)
async def upload_recording(
    entry_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload a voice recording and attach to an entry."""
    svc = VoiceRecordingService(db)
    file_data = await file.read()
    return await svc.upload(entry_id, file.filename or "recording.mp3", file_data)


@router.get("/entry/{entry_id}", response_model=list[VoiceRecordingResponse])
async def list_by_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all recordings for an entry."""
    result = await db.execute(
        select(VoiceRecording).where(VoiceRecording.entry_id == entry_id)
    )
    return result.scalars().all()


@router.post("/{recording_id}/transcribe", response_model=VoiceRecordingResponse)
async def transcribe_recording(recording_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Transcribe a voice recording locally."""
    svc = VoiceRecordingService(db)
    return await svc.transcribe(recording_id)


@router.get("/{recording_id}", response_model=VoiceRecordingResponse)
async def get_recording(recording_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get recording metadata."""
    svc = VoiceRecordingService(db)
    return await svc.get(recording_id)


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(recording_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a recording and its audio file."""
    svc = VoiceRecordingService(db)
    await svc.delete(recording_id)
