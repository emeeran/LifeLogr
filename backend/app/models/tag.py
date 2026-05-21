"""Tag and EntryTag ORM models."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id"), nullable=True)

    children: Mapped[list["Tag"]] = relationship()
    entry_associations: Mapped[list["EntryTag"]] = relationship(  # noqa: F821
        back_populates="tag", cascade="all, delete-orphan"
    )


class EntryTag(Base):
    __tablename__ = "entry_tags"
    __table_args__ = (UniqueConstraint("entry_id", "tag_id"),)

    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)

    entry: Mapped["Entry"] = relationship(back_populates="tag_associations")  # noqa: F821
    tag: Mapped["Tag"] = relationship(back_populates="entry_associations", lazy="selectin")
