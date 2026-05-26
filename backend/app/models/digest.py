"""Digest ORM model — weekly AI-generated journal summaries."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    themes: Mapped[str] = mapped_column(String, nullable=False)  # JSON array of strings
    emotional_trajectory: Mapped[str] = mapped_column(String, nullable=False)
    notable_moments: Mapped[str] = mapped_column(String, nullable=False)  # JSON array of strings
    summary_text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
