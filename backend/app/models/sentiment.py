"""EntrySentiment ORM model — AI-detected emotional analysis of entries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EntrySentiment(Base):
    __tablename__ = "entry_sentiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), unique=True)
    primary_emotion: Mapped[str] = mapped_column(String(50), nullable=False)
    secondary_emotion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intensity: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-10
    valence: Mapped[float] = mapped_column(Float, nullable=False)  # -1.0 to 1.0
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
