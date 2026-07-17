"""EmailFolder ORM model — per-folder IMAP sync state (UIDVALIDITY high-water-mark)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmailFolder(Base):
    """Tracks sync progress for one IMAP folder.

    ``uidvalidity`` + ``last_uid`` implement reliable incremental sync: we only
    FETCH UIDs greater than ``last_uid``. If the server's UIDVALIDITY changes
    (the folder was rebuilt), stored UIDs are invalid and a full re-sync runs.
    """

    __tablename__ = "email_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # IMAP folder name as returned by LIST (e.g. "INBOX", "[Gmail]/Sent Mail").
    folder_name: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    uidvalidity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # "inbox" | "sent" | "drafts" | "trash" | "archive" | "junk" | "other"
    special_use: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("account_id", "folder_name", name="uq_email_folders_account_name"),
    )
