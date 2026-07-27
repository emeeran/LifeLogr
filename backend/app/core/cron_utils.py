"""Cron-expression helpers for the backup/reminder schedulers.

Extracted from ``app.services.scheduler_service`` so the cron -> occurrence math
is unit-testable in isolation. Supports the daily/weekly/monthly 5-field forms
the UI generates (``minute hour day month day_of_week``). Day-of-week follows
APScheduler's convention (0=Monday ... 6=Sunday, matching ``date.weekday()``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

_DOW_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def last_scheduled_occurrence(cron_expr: str, now: datetime) -> datetime | None:
    """Most recent datetime <= *now* matching *cron_expr*, or None if unparseable."""
    parts = cron_expr.split()
    if len(parts) != 5:
        return None
    try:
        hour = int(parts[1])
        minute = int(parts[0])
    except ValueError:
        return None
    dom_field, month_field, dow_field = parts[2], parts[3], parts[4]

    def dom_ok(d: date) -> bool:
        if dom_field == "*":
            return True
        if dom_field == "L":  # last day of month
            last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            return d.day == last.day
        try:
            return d.day == int(dom_field)
        except ValueError:
            return True  # unsupported form — don't constrain

    def month_ok(d: date) -> bool:
        if month_field == "*":
            return True
        try:
            return d.month == int(month_field)
        except ValueError:
            return True

    def dow_ok(d: date) -> bool:
        if dow_field == "*":
            return True
        for tok in str(dow_field).split(","):
            tok = tok.strip().lower()
            if tok in _DOW_NAMES:
                if d.weekday() == _DOW_NAMES[tok]:
                    return True
            else:
                try:
                    if d.weekday() == int(tok):
                        return True
                except ValueError:
                    continue
        return False

    for back in range(37):
        d = (now - timedelta(days=back)).date()
        if dom_ok(d) and month_ok(d) and dow_ok(d):
            cand = datetime(d.year, d.month, d.day, hour, minute)
            if cand <= now:
                return cand
    return None
