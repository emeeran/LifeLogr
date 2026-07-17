"""Voice recording route handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import VoiceRecording
from app.schemas.recording import VoiceRecordingResponse
from app.services.recording_service import VoiceRecordingService

router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])
logger = logging.getLogger(__name__)


@router.post("", response_model=VoiceRecordingResponse, status_code=201)
async def upload_recording(
    entry_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload a voice recording and attach to an entry."""
    svc = VoiceRecordingService(db)
    file_data = await file.read()
    # Reject empty uploads — a 0-byte recording produces a broken file that
    # can never play ("NotSupportedError" in the player). The frontend also
    # guards this, but defend in depth.
    if not file_data:
        raise HTTPException(
            status_code=400,
            detail="Recording is empty (0 bytes). The microphone may not have captured audio.",
        )
    return await svc.upload(entry_id, file.filename or "recording.mp3", file_data)


@router.post("/start")
async def start_recording_route(
    entry_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Begin capturing the microphone via the backend sidecar.

    Used by the desktop app where the webview's (WebKit2GTK) MediaRecorder is
    unreliable. Capture runs here in the backend process (PulseAudio/ALSA).
    """
    svc = VoiceRecordingService(db)
    try:
        await svc.start_recording(entry_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "entry_id": entry_id}


@router.post("/stop", response_model=VoiceRecordingResponse)
async def stop_recording_route(db: AsyncSession = Depends(get_db)) -> Any:
    """Stop the active capture and persist the recording as a WAV."""
    svc = VoiceRecordingService(db)
    try:
        return await svc.stop_recording()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/entry/{entry_id}", response_model=list[VoiceRecordingResponse])
async def list_by_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List all recordings for an entry."""
    result = await db.execute(select(VoiceRecording).where(VoiceRecording.entry_id == entry_id))
    return result.scalars().all()


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
