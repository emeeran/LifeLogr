"""DailyPrompt ORM model."""
from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DailyPrompt(Base):
    __tablename__ = "daily_prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_text: Mapped[str] = mapped_column(String, nullable=False)
    active_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
