"""Contact ORM model — address book entries.

Contacts come from three sources, tracked by ``source``:
  * ``manual`` — user-created via the UI
  * ``email``  — auto-extracted from email correspondence
  * ``vcard``  — imported from a .vcf file

The merge policy during email auto-extraction never overwrites user-curated
data: ``manual``/``vcard`` contacts only get ``last_seen_at`` touched, while
``email`` contacts may have their name enriched when empty.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.contact_group import ContactGroup, contact_group_members


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Canonical display name (manual override wins over auto-extracted).
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Primary email — lowercased, unique. Dedup key for auto-extraction.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # Additional email addresses.
    emails_extra: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Phones: rich multi-value list [{type, value}] is the source of truth.
    # ``phone``/``phone_secondary`` are mirrored from the list (first two) so
    # legacy search (Contact.phone.ilike) and older readers keep working.
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone_secondary: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phones: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)  # job title
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profession: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # EPIM-style structured fields.
    addresses: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    im_handles: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    websites: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    dates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    relationships: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # "manual" | "email" | "vcard"
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Provenance: which email account produced this contact. Plain integer (no
    # FK) so the contacts table can be created independently of email_accounts.
    email_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Path relative to MEDIA_DIR for an avatar/photo.
    photo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    groups: Mapped[list[ContactGroup]] = relationship(
        secondary=contact_group_members, lazy="selectin"
    )
