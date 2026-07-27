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
    unwritable local destination. Never raises — a failure here must not abort
    boot (it reaches the scheduler/DB, which may be mid-init).
    """
    try:
        await _check_backup_health_impl()
    except Exception:
        logger.warning("Backup-health check failed", exc_info=True)
        _backup_result.update(ran=True, scheduled=False, last_run=None, stale=None)


async def _check_backup_health_impl() -> None:
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

# FTS5 virtual tables created by raw DDL (no ORM model) — counted as "expected".
_FTS_TABLES = ("entries_fts", "notes_fts")
# App-created internal tables that aren't ORM-mapped (so absent from
# ``Base.metadata``) but are expected infrastructure — e.g. ``_schema_meta``,
# written by the inline migration system (schema_version + migration_log). It is
# recreated ``IF NOT EXISTS`` every boot, so it is allow-listed here rather than
# required by the missing-tables check.
_INTERNAL_TABLES = ("_schema_meta",)

# Fragmentation/WAL warn thresholds for the maintenance check.
_FRAGMENTATION_THRESHOLD_PCT = 30.0
_WAL_SIZE_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB

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


def _replace_check(checks: list[dict[str, Any]], new: dict[str, Any]) -> None:
    """Replace the check whose id == new['id'] in place, or append if absent."""
    for i, c in enumerate(checks):
        if c["id"] == new["id"]:
            checks[i] = new
            return
    checks.append(new)


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


async def _db_table_names(session: AsyncSession) -> set[str] | None:
    """Actual user-table names from sqlite_master; None if the read failed."""
    try:
        return {
            str(r[0])
            for r in (
                await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            ).fetchall()
        }
    except Exception:
        return None


async def _check_schema_tables(session: AsyncSession) -> dict[str, Any]:
    """Schema completeness: every ORM-mapped table plus the FTS virtual tables."""
    from app.core.database import Base

    expected = set(Base.metadata.tables) | set(_FTS_TABLES)
    actual = await _db_table_names(session)
    if actual is None:
        return _check("schema_tables", "Schema", "error", "Could not read schema.")
    missing = sorted(expected - actual)
    if missing:
        return _check(
            "schema_tables", "Schema", "error", f"Missing table(s): {', '.join(missing)}",
            "Database may be from an incompatible version — back it up and reinitialize.",
        )
    return _check("schema_tables", "Schema", "ok", f"All {len(expected)} expected tables present.")


async def _check_unexpected_tables(session: AsyncSession) -> dict[str, Any]:
    """Tables present that aren't model-mapped or FTS/internal (warn only).

    Allow-lists SQLite internals (``sqlite_*``), FTS5 shadow tables
    (``entries_fts_*`` / ``notes_fts_*``), and app-created internal tables
    (``_schema_meta``) so a healthy DB doesn't false-positive.
    """
    from app.core.database import Base

    expected = set(Base.metadata.tables) | set(_FTS_TABLES)
    actual = await _db_table_names(session)
    if actual is None:
        return _check("unexpected_tables", "Unexpected tables", "error", "Could not read schema.")
    unexpected = sorted(
        t
        for t in actual
        if t not in expected
        and not t.startswith("sqlite_")
        and not t.startswith("entries_fts")
        and not t.startswith("notes_fts")
        and t not in _INTERNAL_TABLES
    )
    if unexpected:
        return _check(
            "unexpected_tables", "Unexpected tables", "warn",
            f"{len(unexpected)} table(s) not in the current schema: {', '.join(unexpected)}",
            "Leftover from an older version — safe to ignore; no active data is stored there.",
        )
    return _check("unexpected_tables", "Unexpected tables", "ok", "No unexpected tables.")


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


async def _check_fragmentation_wal(session: AsyncSession) -> dict[str, Any]:
    """Free-page fragmentation + WAL size (detection only).

    Healing (incremental vacuum) runs in ``check_app_integrity`` after the read
    session closes — it can't run here because the battery holds the size-1 pool.
    """
    from app.core.config import settings

    try:
        freelist = int((await session.execute(text("PRAGMA freelist_count"))).scalar() or 0)
        page_count = int((await session.execute(text("PRAGMA page_count"))).scalar() or 1)
    except Exception as e:
        return _check(
            "db_fragmentation", "DB fragmentation & WAL", "error", f"Could not read pragmas: {e}"
        )
    pct = (freelist / page_count * 100.0) if page_count else 0.0

    wal_path = settings.db_path.parent / (settings.db_path.name + "-wal")
    try:
        wal_kb = wal_path.stat().st_size // 1024 if wal_path.exists() else 0
    except OSError:
        wal_kb = 0

    issues: list[str] = []
    if pct > _FRAGMENTATION_THRESHOLD_PCT:
        issues.append(f"{pct:.0f}% free pages (fragmented)")
    if wal_kb > _WAL_SIZE_THRESHOLD_BYTES // 1024:
        issues.append(f"WAL is {wal_kb // 1024} MB (checkpoint may be stalled)")
    if issues:
        return _check(
            "db_fragmentation", "DB fragmentation & WAL", "warn",
            "; ".join(issues),
            "Run Vacuum from Settings → Data & Backup → Maintenance.",
        )
    return _check(
        "db_fragmentation", "DB fragmentation & WAL", "ok",
        f"{pct:.0f}% free pages; WAL {wal_kb} KB",
    )


async def _check_encryption_key(session: AsyncSession) -> dict[str, Any]:
    from app.core import security
    from app.core.config import settings

    if settings.SECRET_KEY == "change-me-before-production":
        return _check(
            "encryption_key", "Encryption key", "error",
            "Using the default SECRET_KEY — stored cloud credentials cannot be "
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
            "(entries may freeze during backup).", "Increase DB_POOL_SIZE.",
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
    Fixable problems (search-index drift, free-page fragmentation) are
    self-healed after the read pass and the affected checks are re-run so the
    report reflects the repaired state.
    """
    from app.core.database import async_session

    checks: list[dict[str, Any]] = []
    try:
        async with async_session() as session:
            checks.append(await _check_structure(session))
            checks.append(await _check_foreign_keys(session))
            checks.append(await _check_schema_tables(session))
            checks.append(await _check_unexpected_tables(session))
            checks.append(await _check_fts_sync(session))
            checks.append(await _check_encryption_key(session))
            checks.append(await _check_fragmentation_wal(session))
    except Exception as e:
        logger.warning("App-integrity battery could not complete DB checks", exc_info=True)
        checks.append(_check("database", "Database access", "error", f"Could not run DB checks: {e}"))

    # Self-heal fixable problems. Each heal runs on its own committing
    # transaction *after* the read session above has closed — the engine pool
    # is size 1, so opening a second connection while it's held would deadlock.
    healed: list[str] = []
    fts_check = next((c for c in checks if c["id"] == "fts_sync"), None)
    if (
        fts_check is not None
        and fts_check["status"] == "warn"
        and "unavailable" not in fts_check["detail"]
    ):
        try:
            from app.core.database import rebuild_search_index

            await rebuild_search_index()
            healed.append("search index")
        except Exception:
            logger.warning("Search-index self-heal failed", exc_info=True)
    frag_check = next((c for c in checks if c["id"] == "db_fragmentation"), None)
    if (
        frag_check is not None
        and frag_check["status"] == "warn"
        and "fragmented" in frag_check["detail"]
    ):
        try:
            from app.services.scheduler_service import _run_incremental_vacuum

            await _run_incremental_vacuum()
            healed.append("incremental vacuum")
        except Exception:
            logger.warning("Fragmentation self-heal failed", exc_info=True)
    if healed:
        logger.info("Integrity self-healed: %s", ", ".join(healed))
        try:
            async with async_session() as session:
                if any(c["id"] == "fts_sync" and c["status"] == "warn" for c in checks):
                    _replace_check(checks, await _check_fts_sync(session))
                if any(c["id"] == "db_fragmentation" and c["status"] == "warn" for c in checks):
                    _replace_check(checks, await _check_fragmentation_wal(session))
        except Exception:
            logger.warning("Post-heal re-check failed", exc_info=True)

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
