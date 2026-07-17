"""VideoNote ORM model — short video clips attached to journal entries."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


class VideoNote(Base):
    __tablename__ = "video_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    entry: Mapped["Entry"] = relationship()  # noqa: F821
