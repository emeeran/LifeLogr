"""Pydantic schemas for voice recordings."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VoiceRecordingResponse(BaseModel):
    id: int
    entry_id: int
    media_id: int
    duration_seconds: float
    audio_format: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
