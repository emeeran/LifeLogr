"""Cron-expression helpers for the backup/reminder schedulers.

Extracted from ``app.services.scheduler_service`` so the cron -> occurrence math
is unit-testable in isolation. Supports the daily/weekly/monthly 5-field forms
the UI generates (``minute hour day month day_of_week``). Day-of-week follows
APScheduler's convention (0=Monday ... 6=Sunday, matching ``date.weekday()``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

_DOW_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _int_or_none(token: str) -> int | None:
    try:
        return int(token)
    except ValueError:
        return None


def last_scheduled_occurrence(cron_expr: str, now: datetime) -> datetime | None:
    """Most recent datetime <= *now* matching *cron_expr*, or None.

    None also means "unsupported expression" — step/range lists (``*/2``,
    ``1-5``) are not evaluated here, and returning a value for them would make
    the backup catch-up fire on a day the job never runs. Callers must treat
    None as "don't catch up".
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return None
    try:
        hour = int(parts[1])
        minute = int(parts[0])
    except ValueError:
        return None
    dom_field, month_field, dow_field = parts[2], parts[3], parts[4]

    # Validate the day-of-month/month/day-of-week fields up front: an
    # unsupported form must yield "no occurrence", not "matches every day".
    dom_is_last = dom_field == "L"
    dom_day = None if dom_field == "*" or dom_is_last else _int_or_none(dom_field)
    if dom_field != "*" and not dom_is_last and dom_day is None:
        return None
    month = None if month_field == "*" else _int_or_none(month_field)
    if month_field != "*" and month is None:
        return None
    if dow_field != "*":
        for token in dow_field.split(","):
            token = token.strip().lower()
            if token in _DOW_NAMES:
                continue
            if _int_or_none(token) is None:
                return None
    weekdays = (
        None
        if dow_field == "*"
        else {_DOW_NAMES.get(t, _int_or_none(t)) for t in dow_field.split(",")}
    )

    def dom_ok(d: date) -> bool:
        if dom_day is not None:
            return d.day == dom_day
        if dom_is_last:  # last day of month
            last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            return d.day == last.day
        return True  # '*'

    def month_ok(d: date) -> bool:
        return month is None or d.month == month

    def dow_ok(d: date) -> bool:
        return weekdays is None or d.weekday() in weekdays

    for back in range(37):
        d = (now - timedelta(days=back)).date()
        if dom_ok(d) and month_ok(d) and dow_ok(d):
            cand = datetime(d.year, d.month, d.day, hour, minute)
            if cand <= now:
                return cand
    return None
