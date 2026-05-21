"""Global search route handler."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.search import GlobalSearchResponse, SearchMode
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("", response_model=GlobalSearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    mood: str | None = Query(None),
    tag_ids: str | None = Query(None, description="Comma-separated tag IDs"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    mode: SearchMode = Query("hybrid", description="Search mode: keyword, semantic, or hybrid"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Search entries with keyword (FTS5), semantic (embeddings), or hybrid mode."""
    svc = SearchService(db)
    parsed_tag_ids = [int(t) for t in tag_ids.split(",")] if tag_ids else None
    items, total = await svc.search(q, mood, parsed_tag_ids, date_from, date_to, offset, limit, mode)
    return GlobalSearchResponse(items=items, total=total, offset=offset, limit=limit)
