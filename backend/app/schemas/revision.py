"""Pydantic schemas for entry revision history."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RevisionResponse(BaseModel):
    """A single revision snapshot."""

    id: int
    entry_id: int
    revision_number: int
    title: str | None
    body: str
    mood: str | None
    snapshot_reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RevisionDiffResponse(BaseModel):
    """Diff between two revisions."""

    from_revision: int
    to_revision: int
    title_changed: bool
    body_changed: bool
    mood_changed: bool
    from_title: str | None
    to_title: str | None
    from_body: str
    to_body: str
    from_mood: str | None
    to_mood: str | None


class RevisionListResponse(BaseModel):
    """Paginated list of revisions for an entry."""

    items: list[RevisionResponse]
    total: int
    offset: int
    limit: int
