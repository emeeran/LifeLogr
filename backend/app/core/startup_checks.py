"""Startup self-checks: data integrity + backup functionality.

Run once from the app lifespan (``main.py``). Each check logs a clear result and
stashes a small status dict that ``/health`` reads cheaply on every poll — the
checks themselves are not re-run per request.

Design:
- The hard ``PRAGMA integrity_check`` already runs in ``init_db`` (via
  ``validate_db_health``) and *aborts* startup on corruption. These checks are
  additive and **warn-only** — the app must still start so the user can act on a
  degraded backup/integrity state.
- ``check_backup_health`` self-heals the silent-stop failure mode: a schedule row
  present in the DB but no ``auto_backup`` job registered → re-register it.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Stashed results from the last startup run, surfaced via /health. ``ran=False``
# means the check has not completed yet (early in the first boot).
_integrity_result: dict[str, Any] = {"ran": False, "ok": True, "fk_violations": 0}
_backup_result: dict[str, Any] = {
    "ran": False,
    "scheduled": None,
    "last_run": None,
    "stale": None,
}

# A daily backup that hasn't succeeded in >48h (the catch-up window) is suspect.
_STALE_BACKUP_THRESHOLD = timedelta(hours=48)


async def check_data_integrity() -> None:
    """Referential-integrity scan (warn-only).

    ``PRAGMA integrity_check`` (structural corruption) already ran in ``init_db``
    and aborts on failure; this runs ``PRAGMA foreign_key_check`` to catch
    orphaned rows (e.g. a snapshot pointing at a deleted backup config) and logs
    them. Never raises.
    """
    from app.core.database import async_session

    try:
        async with async_session() as session:
            rows = (await session.execute(text("PRAGMA foreign_key_check"))).fetchall()
    except Exception:
        logger.warning("Startup data-integrity check could not run", exc_info=True)
        _integrity_result.update(ran=True, ok=False, fk_violations=-1)
        return

    total = len(rows)
    if total:
        # Each row is (table, rowid, parent, fkid) — keep the report short.
        shown = ", ".join(f"{r[0]}:rowid={r[1]}" for r in rows[:10])
        logger.warning(
            "Startup data-integrity check: %d foreign-key violation(s) — %s",
            total,
            shown,
        )
    else:
        logger.info("Startup data-integrity check: OK")

    _integrity_result.update(ran=True, ok=(total == 0), fk_violations=total)


async def check_backup_health() -> None:
    """Verify the backup system is armed; self-heal if it isn't.

    Catches the silent-stop mode: a ``backup_schedule`` row exists (so the user
    expects daily backups) but the ``auto_backup`` APScheduler job didn't
    register — re-register it. Also warns on a stale/missing last backup and an
    unwritable local destination. Never raises.
    """
    from app.services.scheduler_service import SchedulerService, _get_active_schedule

    active = await _get_active_schedule()
    if active is None:
        logger.info("No backup schedule configured")
        _backup_result.update(ran=True, scheduled=False, last_run=None, stale=None)
        return

    sched = SchedulerService.get_scheduler()
    if sched.get_job("auto_backup") is None:
        if sched.running:
            logger.error(
                "Backup schedule is configured but the auto_backup job is not "
                "registered — re-registering (cron=%s)",
                active.cron,
            )
            await SchedulerService._restore_backup_schedule()
        else:
            logger.error(
                "Backup schedule is configured (cron=%s) but the scheduler is not "
                "running — daily backup will not fire",
                active.cron,
            )

    # Stale-backup detection. last_run_at is stored as UTC; SQLite may strip the
    # tzinfo on read, so treat a naive value as UTC.
    now = datetime.now(timezone.utc)
    last_run = active.last_run_at
    if last_run is not None and last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    stale = last_run is None or (now - last_run) > _STALE_BACKUP_THRESHOLD
    if stale:
        logger.warning(
            "No successful backup since %s — daily backup may not be running",
            last_run.isoformat() if last_run is not None else "never",
        )

    # Local destination writability (cheap). If the folder doesn't exist yet it is
    # created on the first backup, so check the parent it would be made under.
    if active.backup_path:
        dest = active.backup_path
        target = dest if os.path.isdir(dest) else (os.path.dirname(dest) or ".")
        if not os.access(target, os.W_OK):
            logger.warning("Backup destination not writable: %s", dest)

    _backup_result.update(
        ran=True,
        scheduled=(sched.get_job("auto_backup") is not None),
        last_run=(last_run.isoformat() if last_run is not None else None),
        stale=bool(stale),
    )


def get_integrity_status() -> dict[str, Any]:
    """Last data-integrity check result for /health (cheap; no re-run)."""
    return dict(_integrity_result)


def get_backup_status() -> dict[str, Any]:
    """Last backup-health check result for /health (cheap; no re-run)."""
    return dict(_backup_result)
