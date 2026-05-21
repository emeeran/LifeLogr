"""Pydantic schemas for video notes."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VideoNoteResponse(BaseModel):
    """A video note attached to an entry."""
    id: int
    entry_id: int
    filename: str
    duration_seconds: float | None
    thumbnail_path: str | None
    transcription: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoNoteListResponse(BaseModel):
    items: list[VideoNoteResponse]
    total: int
