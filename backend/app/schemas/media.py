"""Pydantic schemas for media attachments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediaCreate(BaseModel):
    entry_id: int = Field(description="Entry to attach media to")
    caption: str | None = Field(default=None, max_length=500, description="Optional caption")

    model_config = ConfigDict(
        json_schema_extra={"example": {"entry_id": 1, "caption": "Sunset photo"}}
    )


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
