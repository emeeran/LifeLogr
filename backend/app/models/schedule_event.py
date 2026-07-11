"""ScheduleEvent ORM model — calendar events/appointments with optional RRULE."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScheduleEvent(Base):
    """A scheduled event. Recurring events store an RFC 5545 ``rrule`` string.

    Occurrences are expanded on demand (see PlannerService.get_agenda) via
    ``dateutil.rrule`` rather than materialized as rows. ``excluded_dates``
    holds ISO dates of individual occurrences the user deleted.
    """

    __tablename__ = "schedule_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Naive local datetimes (single-user desktop app, like Reminders).
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # RFC 5545 RRULE, e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20251231T235959Z".
    # NULL = non-recurring one-off.
    rrule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timezone_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # List of ISO date strings to skip when expanding a recurring series.
    excluded_dates: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_schedule_events_start", "start_at"),)
