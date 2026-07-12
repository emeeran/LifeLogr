"""Pydantic schemas for global search."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


SearchMode = Literal["keyword", "semantic", "hybrid"]


class SearchResultEntry(BaseModel):
    """A single search result.

    ``type`` discriminates entries from notes. Notes have no ``entry_date``
    (they are not date-bound); callers should read ``updated_at`` instead.
    """

    id: int
    type: Literal["entry", "note", "task"] = "entry"
    entry_date: date | None = None
    folder_id: int | None = None
    updated_at: datetime | None = None
    title: str | None
    snippet: str
    rank: float
    similarity_score: float | None = None

    model_config = ConfigDict(from_attributes=True)


class GlobalSearchResponse(BaseModel):
    """Paginated search results."""

    items: list[SearchResultEntry]
    total: int
    offset: int
    limit: int
