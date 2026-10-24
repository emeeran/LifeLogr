"""Pydantic schemas for journal entries."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tag import TagBrief


class EntryCreate(BaseModel):
    entry_date: date
    title: str | None = Field(default=None, max_length=255, description="Entry title")
    body: str = Field(
        default="",
        max_length=1_000_000,
        description="Markdown body (may be empty for title-only/recording-only entries)",
    )
    mood: str | None = Field(default=None, max_length=50, description="Mood label")
    tag_ids: list[int] = Field(default_factory=list, description="Tag IDs to associate")
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Latitude")
    longitude: float | None = Field(default=None, ge=-180, le=180, description="Longitude")
    template_id: int | None = Field(
        default=None, description="ID of the template this entry was created from, if any"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entry_date": "2026-05-08",
                "title": "A great day",
                "body": "Today I built my journal.",
                "mood": "excited",
                "tag_ids": [1],
                "latitude": 52.52,
                "longitude": 13.405,
            }
        }
    )


class ResetRequest(BaseModel):
    """Confirmation payload for the destructive database reset."""

    confirm: str = Field(description='Must be exactly "RESET"')


class EntryUpdate(BaseModel):
    title: str | None = Field(
        default=None, max_length=255, description="Updated title; null to clear"
    )
    body: str | None = Field(
        default=None,
        max_length=1_000_000,
        description="Updated Markdown body; may be empty for title-only/recording-only entries",
    )
    mood: str | None = Field(default=None, max_length=50, description="Updated mood; null to clear")
    tag_ids: list[int] | None = Field(
        default=None, description="Tag IDs to associate; null to keep existing"
    )
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Latitude")
    longitude: float | None = Field(default=None, ge=-180, le=180, description="Longitude")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Updated title",
                "body": "Updated thoughts.",
                "mood": "calm",
                "tag_ids": [1, 2],
                "latitude": 52.52,
                "longitude": 13.405,
            }
        }
    )


class ImportSkipReason(BaseModel):
    """Why one imported record was skipped (index is its 0-based list position)."""

    index: int
    entry_date: str | None = None
    title: str | None = None
    reason: str


class ImportResult(BaseModel):
    """Result of an entry import; ``skip_reasons`` explains every skipped record."""

    imported: int
    skipped: int
    skip_reasons: list[ImportSkipReason] = Field(default_factory=list)


class EntryResponse(BaseModel):
    id: int
    entry_date: date
    title: str | None
    body: str
    summary: str | None = None
    mood: str | None
    is_deleted: bool
    is_encrypted: bool = False
    tags: list[TagBrief]
    media_count: int
    has_recording: bool
    latitude: float | None = None
    longitude: float | None = None
    location_name: str | None = None
    template_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntryListItem(BaseModel):
    """Lightweight entry for list/timeline views.

    Same as :class:`EntryResponse` but with the full ``body`` replaced by a
    server-side ``body_snippet`` (≈300 chars), so list queries don't materialize
    every entry's full body into memory. The single GET keeps ``EntryResponse``.
    """

    id: int
    entry_date: date
    title: str | None
    body_snippet: str
    summary: str | None = None
    mood: str | None
    is_deleted: bool
    is_encrypted: bool = False
    tags: list[TagBrief]
    media_count: int
    has_recording: bool
    latitude: float | None = None
    longitude: float | None = None
    location_name: str | None = None
    template_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalendarEntryResponse(BaseModel):
    """Lightweight entry projection for calendar grid rendering.

    Excludes ``body``, ``summary``, ``media_count``, timestamps, and
    location — fields the calendar grid never reads. This keeps the
    ``/calendar/{year}/{month}`` payload small even for months with many
    long entries.
    """

    id: int
    entry_date: date
    title: str | None
    mood: str | None
    is_encrypted: bool = False
    tags: list[TagBrief]


class EntryListResponse(BaseModel):
    items: list[EntryListItem]
    total: int
    offset: int
    limit: int
