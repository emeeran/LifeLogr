"""EmailMessage ORM model — a parsed, locally-stored email."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmailMessage(Base):
    """One email message. Bodies/snippets live in the DB; the raw ``.eml`` and
    attachment binaries live on disk under ``MEDIA_DIR/email/`` (``raw_path``
    is relative to ``MEDIA_DIR``)."""

    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_id: Mapped[int] = mapped_column(
        ForeignKey("email_folders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    # Threading
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    references: Mapped[str | None] = mapped_column(String, nullable=True)

    # Parsed headers
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_addresses: Mapped[list] = mapped_column(JSON, nullable=False)
    cc_addresses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    bcc_addresses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Bodies
    text_body: Mapped[str | None] = mapped_column(String, nullable=True)
    html_body: Mapped[str | None] = mapped_column(String, nullable=True)
    snippet: Mapped[str | None] = mapped_column(String(500), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Flags (comma-sep IMAP flags) + denormalized booleans for fast filtering.
    flags: Mapped[str] = mapped_column(String, default="", nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    raw_path: Mapped[str | None] = mapped_column(String, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("folder_id", "uid", name="uq_email_messages_folder_uid"),
        Index("ix_email_messages_account_sent", "account_id", "sent_at"),
        Index("ix_email_messages_account_read", "account_id", "is_read"),
    )
