"""EmailAccount ORM model — IMAP/SMTP account with encrypted credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmailAccount(Base):
    """An IMAP/SMTP mailbox. The app password is stored AES-encrypted."""

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    # IMAP connection
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # SMTP connection
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    username: Mapped[str] = mapped_column(String(320), nullable=False)
    # AES-256-GCM ciphertext (app/core/security.encrypt()).
    password_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Sync config
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
