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

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Canonical display name (manual override wins over auto-extracted).
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Primary email — lowercased, unique. Dedup key for auto-extraction.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # Additional email addresses.
    emails_extra: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone_secondary: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)  # job title
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
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
