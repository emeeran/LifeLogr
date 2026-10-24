"""Pydantic schemas for note media attachments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteMediaResponse(BaseModel):
    id: int
    note_id: int
    filename: str
    media_type: str
    file_size: int
    caption: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteMediaFromPath(BaseModel):
    """Import a local file by absolute path (used by Tauri native drag-drop)."""

    path: str = Field(min_length=1, description="Absolute path to a local file to import")
    caption: str | None = Field(default=None, max_length=500)
