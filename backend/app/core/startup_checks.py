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
from sqlalchemy.ext.asyncio import AsyncSession

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


# ── App-integrity battery ────────────────────────────────────────────────────
# A broad, warn-only battery surfaced via /api/v1/system/integrity and /health.
# The hard structural ``PRAGMA integrity_check`` already aborted boot in
# ``init_db``; this adds quick_check + schema/FTS/encryption-key/pool/data-dir
# checks so problems are visible in the UI instead of buried in logs.

# Tables whose absence indicates an incompatible/empty database.
_CRITICAL_TABLES = (
    "entries", "notes", "tags", "media",
)

# (table, column) holding AES-encrypted credentials — the encryption-key canary
# decrypts one row of each to verify the active SECRET_KEY matches.
_CREDENTIAL_PROBES = (
    ("backup_config", "credentials_encrypted"),
)

_app_integrity_result: dict[str, Any] = {
    "ran": False,
    "ran_at": None,
    "checks": [],
    "summary": {"ok": 0, "warn": 0, "error": 0},
}


def _check(
    check_id: str, label: str, status: str, detail: str, hint: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"id": check_id, "label": label, "status": status, "detail": detail}
    if hint:
        out["hint"] = hint
    return out


async def _check_structure(session: AsyncSession) -> dict[str, Any]:
    try:
        res = (await session.execute(text("PRAGMA quick_check"))).scalar()
    except Exception as e:
        return _check("database_structure", "Database structure", "error", f"Could not run quick_check: {e}")
    if res == "ok":
        return _check("database_structure", "Database structure", "ok", "No corruption detected.")
    return _check(
        "database_structure", "Database structure", "error", f"Corruption detected: {res}",
        "Restore the database from a recent backup.",
    )


async def _check_foreign_keys(session: AsyncSession) -> dict[str, Any]:
    try:
        rows = (await session.execute(text("PRAGMA foreign_key_check"))).fetchall()
    except Exception as e:
        return _check("foreign_keys", "Referential integrity", "error", f"Could not run: {e}")
    if not rows:
        return _check("foreign_keys", "Referential integrity", "ok", "No orphaned rows.")
    shown = ", ".join(f"{r[0]}:rowid={r[1]}" for r in rows[:5])
    return _check(
        "foreign_keys", "Referential integrity", "warn",
        f"{len(rows)} orphaned row(s): {shown}", "Re-link or remove orphaned records.",
    )


async def _check_schema_tables(session: AsyncSession) -> dict[str, Any]:
    missing: list[str] = []
    for t in _CRITICAL_TABLES:
        try:
            exists = (
                await session.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": t}
                )
            ).scalar()
        except Exception:
            exists = None
        if not exists:
            missing.append(t)
    if missing:
        return _check(
            "schema_tables", "Schema", "error", f"Missing table(s): {', '.join(missing)}",
            "Database may be from an incompatible version — back it up and reinitialize.",
        )
    return _check("schema_tables", "Schema", "ok", "All critical tables present.")


async def _check_fts_sync(session: AsyncSession) -> dict[str, Any]:
    drift: list[str] = []
    for base, fts in (("entries", "entries_fts"), ("notes", "notes_fts")):
        try:
            base_n = (
                await session.execute(
                    text(f"SELECT COUNT(*) FROM {base} WHERE is_deleted=0 AND is_encrypted=0")
                )
            ).scalar() or 0
            fts_n = (await session.execute(text(f"SELECT COUNT(*) FROM {fts}"))).scalar() or 0
        except Exception:
            drift.append(f"{fts}: unavailable")
            continue
        if fts_n != base_n:
            drift.append(f"{fts}: {fts_n} indexed (expected {base_n})")
    if drift:
        return _check(
            "fts_sync", "Search index", "warn", "Out of sync: " + "; ".join(drift),
            "Rebuild the search index from Settings → Diagnostics.",
        )
    return _check("fts_sync", "Search index", "ok", "Index in sync.")


async def _check_encryption_key(session: AsyncSession) -> dict[str, Any]:
    from app.core import security
    from app.core.config import settings

    if settings.SECRET_KEY == "change-me-before-production":
        return _check(
            "encryption_key", "Encryption key", "error",
            "Using the default SECRET_KEY — stored email/cloud credentials cannot be "
            "decrypted safely.",
            "Set a SECRET_KEY (the packaged app manages this via .secret_key).",
        )
    mismatches: list[str] = []
    checked = 0
    for table, col in _CREDENTIAL_PROBES:
        try:
            value = (await session.execute(text(f"SELECT {col} FROM {table} LIMIT 1"))).scalar()
        except Exception:
            continue  # table/column may not exist on older schemas
        if not value:
            continue
        checked += 1
        try:
            security.decrypt(value)
        except Exception:
            mismatches.append(table)
    if mismatches:
        return _check(
            "encryption_key", "Encryption key", "error",
            f"Credential decryption failed for: {', '.join(mismatches)}. The active key does "
            "not match the one that encrypted them.",
            "Re-enter the password / reconnect the account, or restore .secret_key.",
        )
    if checked == 0:
        return _check("encryption_key", "Encryption key", "ok", "No stored credentials to verify.")
    return _check("encryption_key", "Encryption key", "ok", f"Verified {checked} stored credential(s) decrypt.")


def _check_connection_pool() -> dict[str, Any]:
    from app.core.config import settings
    detail = f"pool_size={settings.DB_POOL_SIZE}, max_overflow={settings.DB_MAX_OVERFLOW}"
    if settings.DB_POOL_SIZE <= 1:
        return _check(
            "connection_pool", "Connection pool", "warn",
            f"{detail} — a single connection can be saturated by long background jobs "
            "(entries may freeze during email sync / backup).", "Increase DB_POOL_SIZE.",
        )
    return _check("connection_pool", "Connection pool", "ok", detail)


def _check_data_dir() -> dict[str, Any]:
    from app.core.config import settings
    issues: list[str] = []
    dd = settings.DATA_DIR
    if not (dd.exists() and os.access(dd, os.W_OK)):
        issues.append(f"{dd} not writable")
    db = settings.db_path
    if not (db.exists() and db.stat().st_size > 0):
        issues.append(f"{db.name} missing or empty")
    if os.environ.get("DATA_DIR") and not (dd / ".secret_key").exists():
        issues.append(".secret_key missing (desktop sidecar)")
    for sub in ("media", "tts"):
        if not (dd / sub).is_dir():
            issues.append(f"{sub}/ missing")
    if issues:
        return _check("data_dir", "Data directory", "warn", "; ".join(issues))
    return _check("data_dir", "Data directory", "ok", str(dd))


def _check_backup_status_folded() -> dict[str, Any]:
    b = get_backup_status()
    if not b.get("ran"):
        return _check("backup", "Backups", "warn", "Not checked yet at boot.")
    if b.get("stale"):
        return _check("backup", "Backups", "warn", "No successful backup in >48h.", "Run a backup now.")
    if b.get("scheduled"):
        return _check("backup", "Backups", "ok", "Scheduled and recent.")
    return _check("backup", "Backups", "warn", "No backup schedule configured.")


def _check_scheduler() -> dict[str, Any]:
    try:
        from app.services.scheduler_service import SchedulerService
        sched = SchedulerService.get_scheduler()
        if getattr(sched, "running", False):
            return _check("scheduler", "Scheduler", "ok", f"{len(sched.get_jobs())} job(s) registered.")
        return _check("scheduler", "Scheduler", "warn", "Scheduler is not running.")
    except Exception as e:
        return _check("scheduler", "Scheduler", "warn", f"Could not inspect scheduler: {e}")


async def check_app_integrity() -> dict[str, Any]:
    """Run the full app-integrity battery; cache and return the report.

    Warn-only — never raises; a failing check is reported, not propagated.
    """
    from app.core.database import async_session

    checks: list[dict[str, Any]] = []
    try:
        async with async_session() as session:
            checks.append(await _check_structure(session))
            checks.append(await _check_foreign_keys(session))
            checks.append(await _check_schema_tables(session))
            checks.append(await _check_fts_sync(session))
            checks.append(await _check_encryption_key(session))
    except Exception as e:
        logger.warning("App-integrity battery could not complete DB checks", exc_info=True)
        checks.append(_check("database", "Database access", "error", f"Could not run DB checks: {e}"))

    checks.append(_check_connection_pool())
    checks.append(_check_data_dir())
    checks.append(_check_backup_status_folded())
    checks.append(_check_scheduler())

    summary = {
        "ok": sum(1 for c in checks if c["status"] == "ok"),
        "warn": sum(1 for c in checks if c["status"] == "warn"),
        "error": sum(1 for c in checks if c["status"] == "error"),
    }
    report: dict[str, Any] = {
        "ran": True,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "summary": summary,
    }
    _app_integrity_result.clear()
    _app_integrity_result.update(report)
    return report


def get_app_integrity() -> dict[str, Any]:
    """Last app-integrity report (cheap; no re-run)."""
    return dict(_app_integrity_result)
