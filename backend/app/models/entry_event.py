"""EntryEvent ORM model — typed per-entry events (weather today, more later).

Rows come from Diarium ``.diary`` imports: ``Events.Type=0`` is verified
weather (``Content`` like ``"84 / 74 °F"``, ``Tag`` the condition label);
other Type values are unverified vendor enums, carried verbatim as
``kind="unknown:<n>"`` so nothing is dropped and a future re-migration can
re-classify them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entry import Entry

# Verified Events.Type values (see docs/diarium-format-analysis.md §3.5).
KIND_WEATHER = "weather"


def event_kind_for_type(type_value: int | None) -> str:
    """Map a Diarium ``Events.Type`` to our ``kind`` string.

    Type 0 is verified weather; every other value (including NULL) is an
    unverified vendor enum, carried as ``unknown:<n>`` rather than dropped.
    """
    if type_value == 0:
        return KIND_WEATHER
    return f"unknown:{type_value}"


class EntryEvent(Base):
    __tablename__ = "entry_events"
    __table_args__ = (Index("ix_entry_events_entry_id", "entry_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    entry: Mapped["Entry"] = relationship(  # noqa: F821
        back_populates="events"
    )
