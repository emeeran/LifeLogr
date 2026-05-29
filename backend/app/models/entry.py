"""Entry ORM model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.media import Media
    from app.models.recording import VoiceRecording
    from app.models.tag import EntryTag


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encrypted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_entries_deleted_date", "is_deleted", "entry_date"),
        Index("ix_entries_deleted_mood", "is_deleted", "mood"),
    )

    tag_associations: Mapped[list["EntryTag"]] = relationship(  # noqa: F821
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )
    media: Mapped[list["Media"]] = relationship(  # noqa: F821
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )
    recordings: Mapped[list["VoiceRecording"]] = relationship(  # noqa: F821
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )
