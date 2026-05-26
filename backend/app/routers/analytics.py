"""Analytics route handlers — journal statistics and insights."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.analytics import (
    HeatmapResponse,
    MediaStatsResponse,
    MoodDistributionResponse,
    OverviewResponse,
    TagStatsResponse,
    WordCountResponse,
    WritingHabitResponse,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(db: AsyncSession = Depends(get_db)) -> Any:
    """High-level journal statistics."""
    svc = AnalyticsService(db)
    return await svc.overview()


@router.get("/habits", response_model=list[WritingHabitResponse])
async def get_writing_habits(db: AsyncSession = Depends(get_db)) -> Any:
    """Writing frequency per day of week."""
    svc = AnalyticsService(db)
    return await svc.writing_habits()


@router.get("/words", response_model=WordCountResponse)
async def get_word_counts(db: AsyncSession = Depends(get_db)) -> Any:
    """Word count statistics."""
    svc = AnalyticsService(db)
    return await svc.word_counts()


@router.get("/tags", response_model=list[TagStatsResponse])
async def get_tag_stats(db: AsyncSession = Depends(get_db)) -> Any:
    """Tag usage counts."""
    svc = AnalyticsService(db)
    return await svc.tag_stats()


@router.get("/moods", response_model=list[MoodDistributionResponse])
async def get_mood_distribution(db: AsyncSession = Depends(get_db)) -> Any:
    """Mood frequency distribution."""
    svc = AnalyticsService(db)
    return await svc.mood_distribution()


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(year: int | None = Query(None)) -> Any:
    """Year-long contribution heatmap."""
    from app.core.database import async_session

    async with async_session() as db:
        svc = AnalyticsService(db)
        return await svc.heatmap(year)


@router.get("/media", response_model=MediaStatsResponse)
async def get_media_stats(db: AsyncSession = Depends(get_db)) -> Any:
    """Media usage statistics."""
    svc = AnalyticsService(db)
    return await svc.media_stats()


@router.get("/sentiment-timeline")
async def get_sentiment_timeline(
    year: int = Query(..., description="Year"),
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Valence over time for AI-analyzed entries."""
    svc = AnalyticsService(db)
    return await svc.sentiment_timeline(year, month)
