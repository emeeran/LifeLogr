"""Note, NoteFolder, and NoteTag ORM models.

Notes are standalone, non-date-bound records (knowledge-base style), in
contrast to date-bound journal ``entries``. They reuse the shared ``tags``
table via the ``NoteTag`` junction (mirroring ``EntryTag``).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.note_media import NoteMedia
    from app.models.tag import Tag


class NoteFolder(Base):
    """A notebook/folder that groups notes."""

    __tablename__ = "note_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Self-FK reserved for nested folders; UI is flat in v1 (no relationship).
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("note_folders.id", ondelete="SET NULL"), nullable=True
    )
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_note_folders_deleted", "is_deleted"),)

    notes: Mapped[list["Note"]] = relationship(  # noqa: F821
        back_populates="folder", cascade="all, delete-orphan", lazy="selectin"
    )


class Note(Base):
    """A standalone note (markdown body, optional title/folder/tags/pin)."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # SET NULL so deleting a folder un-files its notes rather than hard-deleting
    # them — consistent with the app's soft-delete philosophy.
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("note_folders.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encrypted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Random per-note PBKDF2 salt (base64). Null on legacy notes encrypted
    # before salts were introduced (decrypted via the deterministic fallback).
    encryption_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_notes_folder_pinned_updated", "is_deleted", "folder_id", "is_pinned", "updated_at"
        ),
        Index("ix_notes_deleted_updated", "is_deleted", "updated_at"),
    )

    folder: Mapped["NoteFolder | None"] = relationship(back_populates="notes")
    tag_associations: Mapped[list["NoteTag"]] = relationship(  # noqa: F821
        back_populates="note", cascade="all, delete-orphan", lazy="selectin"
    )
    media: Mapped[list["NoteMedia"]] = relationship(  # noqa: F821
        back_populates="note", cascade="all, delete-orphan", lazy="selectin"
    )
    pages: Mapped[list["NotePage"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="NotePage.sort_order",
    )


class NoteTag(Base):
    """Many-to-many junction between notes and the shared tags table."""

    __tablename__ = "note_tags"
    __table_args__ = (
        UniqueConstraint("note_id", "tag_id"),
        Index("ix_note_tags_tag_id", "tag_id"),
    )

    note_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    note: Mapped["Note"] = relationship(back_populates="tag_associations")  # noqa: F821
    tag: Mapped["Tag"] = relationship(back_populates="note_associations", lazy="selectin")  # noqa: F821


class NotePage(Base):
    """A tabbed sub-page within a note (EPIM-style page tabs).

    The note's own ``title``/``body`` is the first ("Main") tab and stays the
    source of truth for encryption + FTS search; these rows are the
    supplementary tabs the user can add / rename / reorder / delete.
    """

    __tablename__ = "note_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_note_pages_note_order", "note_id", "sort_order"),)

    note: Mapped["Note"] = relationship(back_populates="pages")
