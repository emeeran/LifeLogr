"""Pydantic schemas for media attachments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaResponse(BaseModel):
    id: int
    entry_id: int
    filename: str
    media_type: str
    file_size: int
    caption: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MediaTimelineItem(MediaResponse):
    entry_date: str
    entry_title: str | None


class MediaTimelineResponse(BaseModel):
    items: list[MediaTimelineItem]
    total: int
