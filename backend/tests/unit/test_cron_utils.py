"""Unit tests for the cron -> occurrence math (extracted from scheduler_service)."""

from __future__ import annotations

from datetime import datetime

from app.core.cron_utils import last_scheduled_occurrence


def test_daily_same_day():
    # "0 2 * * *" = 02:00 daily. At 10:00 the last occurrence is today 02:00.
    assert last_scheduled_occurrence("0 2 * * *", datetime(2026, 1, 15, 10, 0)) == datetime(
        2026, 1, 15, 2, 0
    )


def test_daily_before_time_rolls_back_a_day():
    # At 01:00 (before today's 02:00) the last occurrence is yesterday 02:00.
    assert last_scheduled_occurrence("0 2 * * *", datetime(2026, 1, 15, 1, 0)) == datetime(
        2026, 1, 14, 2, 0
    )


def test_weekly_named_days():
    # "0 9 * * mon,wed,fri" = 09:00 on Mon/Wed/Fri.
    # 2026-01-16 is Friday; 2026-01-15 is Thursday.
    assert last_scheduled_occurrence("0 9 * * mon,wed,fri", datetime(2026, 1, 16, 10, 0)) == datetime(
        2026, 1, 16, 9, 0
    )
    # Thursday doesn't match -> rolls back to Wednesday 2026-01-14 09:00.
    assert last_scheduled_occurrence("0 9 * * mon,wed,fri", datetime(2026, 1, 15, 10, 0)) == datetime(
        2026, 1, 14, 9, 0
    )


def test_monthly_last_day():
    # "0 23 L * *" = 23:00 on the last day of the month. January has 31 days.
    assert last_scheduled_occurrence("0 23 L * *", datetime(2026, 1, 31, 23, 30)) == datetime(
        2026, 1, 31, 23, 0
    )


def test_invalid_expressions_return_none():
    assert last_scheduled_occurrence("not a cron", datetime(2026, 1, 15, 10, 0)) is None
    assert last_scheduled_occurrence("0 2", datetime(2026, 1, 15, 10, 0)) is None  # too few fields
