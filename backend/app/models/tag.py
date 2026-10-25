"""Tag and EntryTag ORM models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry
    from app.models.note import NoteTag


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True
    )
    # Diarium Tags.Type=2 ("track mood, weight or other metrics"): a tag whose
    # per-entry state lives in EntryTag.tracking_value. Set only by the Diarium
    # import for now — tracker creation UI is a follow-up.
    is_tracker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    children: Mapped[list["Tag"]] = relationship()
    entry_associations: Mapped[list["EntryTag"]] = relationship(  # noqa: F821
        back_populates="tag", cascade="all, delete-orphan"
    )
    note_associations: Mapped[list["NoteTag"]] = relationship(  # noqa: F821
        back_populates="tag", cascade="all, delete-orphan"
    )


class EntryTag(Base):
    __tablename__ = "entry_tags"
    __table_args__ = (
        UniqueConstraint("entry_id", "tag_id"),
        Index("ix_entry_tags_tag_id", "tag_id"),
    )

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    # Verbatim tracker reading for this (entry, tracker-tag) pair — imported
    # from Diarium's EntryTags.TrackingValue. Values in the wild are strings
    # of unknown shape ("84/74", "true", "1.5kg"), so stored as-is and parsed
    # at read time; never guess a parser at import.
    tracking_value: Mapped[str | None] = mapped_column(String(500), nullable=True)

    entry: Mapped["Entry"] = relationship(back_populates="tag_associations")  # noqa: F821
    tag: Mapped["Tag"] = relationship(back_populates="entry_associations", lazy="selectin")
