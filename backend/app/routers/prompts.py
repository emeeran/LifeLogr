"""Daily prompt route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.prompt import PromptResponse
from app.services.prompt_service import PromptService

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.get("/today", response_model=PromptResponse)
async def get_today_prompt(db: AsyncSession = Depends(get_db)) -> Any:
    """Get today's writing prompt."""
    svc = PromptService(db)
    return await svc.get_today()
