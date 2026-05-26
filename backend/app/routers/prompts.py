"""Daily prompt route handlers."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.prompt import DailyPrompt
from app.schemas.prompt import PromptResponse

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.get("/today", response_model=PromptResponse)
async def get_today_prompt(db: AsyncSession = Depends(get_db)) -> Any:
    """Get today's writing prompt."""
    today = date.today()
    result = await db.execute(select(DailyPrompt).where(DailyPrompt.active_date == today))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise NotFoundError(f"No prompt for {today}")
    return prompt
