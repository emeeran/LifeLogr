"""VoiceRecording ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry
    from app.models.media import Media


class VoiceRecording(Base):
    __tablename__ = "voice_recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), nullable=False
    )
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    audio_format: Mapped[str] = mapped_column(String(10), nullable=False)
    transcription: Mapped[str | None] = mapped_column(String, nullable=True)
    is_transcribed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    entry: Mapped["Entry"] = relationship(back_populates="recordings")  # noqa: F821
    media: Mapped["Media"] = relationship(back_populates="recording")  # noqa: F821
