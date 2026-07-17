"""Task ORM models — task lists and self-referential tasks (subtasks)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# The stored priority is one of these three literals or NULL.
Priority = Literal["low", "medium", "high"]


class TaskList(Base):
    """User-defined grouping for tasks (e.g. 'Work', 'Personal')."""

    __tablename__ = "task_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ── Google Tasks sync provenance (NULL / 'manual' for user-created) ──
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Task(Base):
    """A todo item. ``parent_id`` links subtasks to a parent task."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    list_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_lists.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # "low" | "medium" | "high" | null
    priority: Mapped[Priority | None] = mapped_column(String(20), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ── Google Tasks sync provenance (NULL / 'manual' for user-created) ──
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    children: Mapped[list["Task"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Task.sort_order",
    )
    parent: Mapped["Task | None"] = relationship(back_populates="children", remote_side="Task.id")

    __table_args__ = (
        Index("ix_tasks_list_completed_sort", "list_id", "is_completed", "sort_order"),
    )
