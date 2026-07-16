"""BackupConfig and BackupSnapshot ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BackupConfig(Base):
    __tablename__ = "backup_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    credentials_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    snapshots: Mapped[list["BackupSnapshot"]] = relationship(back_populates="config")


class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("backup_config.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    entries_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    media_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # Filename of the uploaded archive on the provider (so a snapshot can be
    # deleted from cloud storage). Null for snapshots from older versions.
    backup_filename: Mapped[str | None] = mapped_column(String, nullable=True)

    config: Mapped["BackupConfig"] = relationship(back_populates="snapshots")


class BackupSchedule(Base):
    """The single active backup schedule — the durable source of truth.

    Exactly one row exists (id=1) when a schedule is active; it is deleted on
    unschedule. Both modes are represented: cloud via ``config_id`` (FK to
    ``backup_config``) or local via ``backup_path`` + ``retention``. ``cron`` is
    a 5-field expression.

    This lives in the DB (not a JSON file) so the schedule survives app/data-dir
    relocation and reinstalls — the earlier JSON-only store was silently lost on
    such events, stopping daily backups with no fallback.
    """

    __tablename__ = "backup_schedule"

    # Singleton: only id=1 is ever used.
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    cron: Mapped[str] = mapped_column(String, nullable=False)
    # Cloud mode → the configured provider. SET NULL if the config is deleted
    # (the restore path then treats a NULL config_id with no path as "no
    # schedule" and drops it).
    config_id: Mapped[int | None] = mapped_column(
        ForeignKey("backup_config.id", ondelete="SET NULL"), nullable=True
    )
    # Local mode → destination folder (user-owned space, validated on save).
    backup_path: Mapped[str | None] = mapped_column(String, nullable=True)
    retention: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
