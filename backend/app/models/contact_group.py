"""ContactGroup model + membership association — user-defined categories.

A many-to-many grouping of contacts (e.g. "Family", "Work", "VIP"). Membership
is reconciled from ``group_ids`` by ``ContactService``; the association table is
created automatically by ``Base.metadata.create_all`` alongside this model.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Pure join table: contact ↔ group. No association-object behaviour needed —
# membership is driven entirely by ``ContactService._set_groups``.
contact_group_members = Table(
    "contact_group_members",
    Base.metadata,
    Column(
        "contact_id",
        ForeignKey("contacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "group_id",
        ForeignKey("contact_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ContactGroup(Base):
    __tablename__ = "contact_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
