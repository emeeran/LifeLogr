"""Business logic for daily prompts."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.prompt import DailyPrompt


class PromptService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_today(self) -> DailyPrompt:
        """Return today's writing prompt; raise if none exists."""
        today = date.today()
        result = await self.db.execute(select(DailyPrompt).where(DailyPrompt.active_date == today))
        prompt = result.scalar_one_or_none()
        if not prompt:
            raise NotFoundError(f"No prompt for {today}")
        return prompt
