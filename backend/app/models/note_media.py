"""NoteMedia ORM model — image/file attachments scoped to a note.

Parallel to the entry-scoped ``Media`` model, for inline image embedding in
notes via drag-and-drop / paste.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.note import Note


class NoteMedia(Base):
    __tablename__ = "note_media"
    # Same 25 MB cap as entry media.
    __table_args__ = (CheckConstraint("file_size <= 26214400", name="max_note_media_size"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    note: Mapped["Note"] = relationship(back_populates="media")  # noqa: F821
