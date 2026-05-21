"""Media ORM model."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry
    from app.models.recording import VoiceRecording


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (CheckConstraint("file_size <= 26214400", name="max_media_size"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_inline: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    entry: Mapped["Entry"] = relationship(back_populates="media")  # noqa: F821
    recording: Mapped["VoiceRecording | None"] = relationship(  # noqa: F821
        back_populates="media", uselist=False
    )
