"""EntryRevision ORM model — version history for journal entries."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


class EntryRevision(Base):
    __tablename__ = "entry_revisions"
    __table_args__ = (UniqueConstraint("entry_id", "revision_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    snapshot_reason: Mapped[str] = mapped_column(String(20), default="edit", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    entry: Mapped["Entry"] = relationship()  # noqa: F821
