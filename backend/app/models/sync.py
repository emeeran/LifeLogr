"""SyncQueue and SyncStatus ORM models — offline sync queue."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SyncQueue(Base):
    """Queued operations to flush when connectivity returns."""
    __tablename__ = "sync_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)  # create, update, delete
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # entry, media, tag
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(String, nullable=False)  # JSON-serialized data
    is_synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SyncStatus(Base):
    """Tracks last sync state per provider."""
    __tablename__ = "sync_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)  # idle, syncing, error
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
