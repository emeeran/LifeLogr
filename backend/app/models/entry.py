"""Entry ORM model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry_event import EntryEvent
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
    # Random per-entry PBKDF2 salt (base64). Null on legacy entries encrypted
    # before salts were introduced (decrypted via the deterministic fallback).
    encryption_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Provenance for file-based sync (Diarium .diary / Day One). ``external_id``
    # is the source's own identity — for Diarium that is ``DiaryEntryId``, the
    # .NET tick timestamp, stored as a string because it exceeds JS int safety.
    # ``sync_hash`` is the fingerprint of the text as it stood at the last
    # import, so a later pull can tell "LifeLogr edited this" from "unchanged"
    # (Diarium has no LastModified column to compare against).
    external_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Which template this entry was created from (null = none/blank). Set at
    # creation; SET NULL if the template is ever deleted (templates are
    # hard-deleted in template_service). Enables the Timeline template filter.
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_entries_deleted_date", "is_deleted", "entry_date"),
        Index("ix_entries_deleted_mood", "is_deleted", "mood"),
        # Partial: legacy rows imported before identity tracking have a NULL
        # external_id and must not collide with one another.
        Index(
            "ix_entries_external",
            "external_source",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
        ),
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
    events: Mapped[list["EntryEvent"]] = relationship(  # noqa: F821
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )
