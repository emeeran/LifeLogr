"""GoogleSyncAccount ORM model — one Google OAuth connection for Calendar+Tasks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GoogleSyncAccount(Base):
    """A single Google account connection used for Calendar + Tasks sync.

    Holds the encrypted OAuth token (scopes: ``calendar`` + ``tasks``) plus
    per-service incremental-sync cursors and state. One row per Google account
    (a singleton in practice — the app is single-user). Gmail stays on its own
    IMAP connection and is not represented here.
    """

    __tablename__ = "google_sync_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    # AES-encrypted JSON: {client_id, client_secret, access_token, refresh_token,
    # token_expiry} — same shape as BackupConfig credentials.
    credentials_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tasks_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Incremental sync cursors (NULL = no incremental state yet → full sync).
    calendar_sync_token: Mapped[str | None] = mapped_column(String, nullable=True)
    # Tasks API has no sync token; this is an ISO timestamp used as updatedMin.
    tasks_sync_token: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
