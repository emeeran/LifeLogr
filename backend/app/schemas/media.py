"""Pydantic schemas for media attachments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediaResponse(BaseModel):
    id: int
    entry_id: int
    filename: str
    media_type: str
    file_size: int
    caption: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MediaFromPath(BaseModel):
    """Import a local file by absolute path (used by Tauri native drag-drop)."""

    entry_id: int = Field(description="Entry the imported file attaches to")
    path: str = Field(min_length=1, description="Absolute path to a local file to import")
    caption: str | None = Field(default=None, max_length=500)


class MediaTimelineItem(MediaResponse):
    entry_date: str
    entry_title: str | None


class MediaTimelineResponse(BaseModel):
    items: list[MediaTimelineItem]
    total: int
