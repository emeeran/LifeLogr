"""Automated backup scheduling with APScheduler and cloud provider support."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Any = None


class ScheduleEntry(TypedDict, total=False):
    """Persisted active backup schedule, round-tripped through JSON on disk.

    ``cron`` is always present; then either ``config_id`` (cloud mode) or
    ``backup_path`` + ``retention`` (local mode). ``last_run`` is optional.
    """

    cron: str
    config_id: int
    backup_path: str
    retention: int
    last_run: str


# ── Schedule persistence (DB-backed; source of truth) ────────────────────
# The active schedule lives as a singleton row (id=1) in ``backup_schedule``.
# APScheduler's default job store is in-memory, so the ``auto_backup`` job
# vanishes on every process exit; ``_restore_backup_schedule`` re-registers it
# from the DB on startup.
#
# The DB survives app restarts, data-dir relocations and reinstalls. The
# earlier JSON-only store (``.backup-schedule.json``) did not — it was silently
# lost on such events, stopping daily backups with no fallback. That file is now
# only a one-time legacy input, migrated into the DB on the first post-upgrade
# boot (see ``_restore_backup_schedule``).

_SCHEDULE_ID = 1  # the single active-schedule row


@dataclass(slots=True)
class ActiveSchedule:
    """Snapshot of the active schedule row (plain data; safe off the session)."""

    cron: str
    config_id: int | None
    backup_path: str | None
    retention: int
    last_run_at: datetime | None


def _schedule_store_path() -> Path:
    """Path to the *legacy* on-disk schedule (migration input only)."""
    from app.core.config import settings

    return Path(settings.DATA_DIR) / ".backup-schedule.json"


def _load_legacy_schedule() -> ScheduleEntry | None:
    """Read the legacy on-disk schedule, or None if absent/unreadable.

    Used only by the one-time migration in ``_restore_backup_schedule``.
    """
    path = _schedule_store_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # JSON structure isn't statically verifiable; trust the on-disk shape
        # (written by the legacy code path with a ScheduleEntry).
        return cast(ScheduleEntry, data) if isinstance(data, dict) else None
    except Exception:
        logger.warning("Failed to read legacy backup schedule", exc_info=True)
        return None


def _clear_legacy_schedule() -> None:
    """Remove the legacy on-disk schedule (best-effort)."""
    try:
        _schedule_store_path().unlink(missing_ok=True)
    except Exception:
        logger.warning("Failed to clear legacy backup schedule", exc_info=True)


async def _save_schedule(entry: ScheduleEntry) -> None:
    """Upsert the singleton active-schedule row (source of truth).

    ``last_run_at`` is intentionally not written here, so re-saving a schedule
    preserves the existing run history.
    """
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.backup import BackupSchedule

    async with async_session() as session:
        row = (
            await session.execute(
                select(BackupSchedule).where(BackupSchedule.id == _SCHEDULE_ID)
            )
        ).scalar_one_or_none()
        if row is None:
            row = BackupSchedule(id=_SCHEDULE_ID, cron=entry["cron"])
            session.add(row)
        row.cron = entry["cron"]
        row.config_id = entry.get("config_id")
        row.backup_path = entry.get("backup_path")
        row.retention = int(entry.get("retention", 10) or 10)
        await session.commit()


async def _get_active_schedule() -> ActiveSchedule | None:
    """Return the active schedule as a plain record (read while the session is open)."""
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.backup import BackupSchedule

    async with async_session() as session:
        row = (
            await session.execute(
                select(BackupSchedule).where(BackupSchedule.id == _SCHEDULE_ID)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return ActiveSchedule(
            cron=row.cron,
            config_id=row.config_id,
            backup_path=row.backup_path,
            retention=row.retention,
            last_run_at=row.last_run_at,
        )


async def _delete_schedule() -> None:
    """Remove the active-schedule row (called on unschedule)."""
    from sqlalchemy import delete

    from app.core.database import async_session
    from app.models.backup import BackupSchedule

    async with async_session() as session:
        await session.execute(
            delete(BackupSchedule).where(BackupSchedule.id == _SCHEDULE_ID)
        )
        await session.commit()


async def _mark_backup_run() -> None:
    """Stamp the active schedule with the time of the last successful run.

    The startup catch-up sweep uses this to tell a missed backup from one that
    already ran today.
    """
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.backup import BackupSchedule

    async with async_session() as session:
        row = (
            await session.execute(
                select(BackupSchedule).where(BackupSchedule.id == _SCHEDULE_ID)
            )
        ).scalar_one_or_none()
        if row is not None:
            row.last_run_at = datetime.now(timezone.utc)
            await session.commit()


async def _set_config_schedule_cron(config_id: int, cron: str) -> None:
    """Keep ``backup_config.schedule_cron`` in sync for a cloud schedule.

    The DB ``backup_schedule`` row is the scheduler's source of truth; this only
    mirrors the cron onto the config row so the legacy column isn't misleading.
    """
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.backup import BackupConfig

    async with async_session() as session:
        cfg = (
            await session.execute(select(BackupConfig).where(BackupConfig.id == config_id))
        ).scalar_one_or_none()
        if cfg is not None:
            cfg.schedule_cron = cron
            await session.commit()


async def _clear_config_schedule_cron() -> None:
    """Clear ``schedule_cron`` on every config (the active schedule was removed)."""
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.backup import BackupConfig

    async with async_session() as session:
        configs = (
            (
                await session.execute(
                    select(BackupConfig).where(BackupConfig.schedule_cron.isnot(None))
                )
            )
            .scalars()
            .all()
        )
        if not configs:
            return
        for cfg in configs:
            cfg.schedule_cron = None
        await session.commit()


def _last_scheduled_occurrence(cron_expr: str, now: datetime) -> datetime | None:
    """Most recent datetime ≤ *now* matching *cron_expr*.

    Supports the daily/weekly/monthly forms the UI generates
    (``minute hour day month day_of_week``). Day-of-week uses APScheduler's
    convention (0=Monday … 6=Sunday, matching ``date.weekday()``). Returns
    None for unparseable expressions.
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

    _DOW_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

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


class SchedulerService:
    """Manages automated backup scheduling."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def get_scheduler() -> Any:
        global _scheduler
        if _scheduler is None:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            _scheduler = AsyncIOScheduler()
        return _scheduler

    @staticmethod
    def _cron_trigger(cron_expr: str) -> Any:
        """Build an APScheduler CronTrigger from a 5-field cron expression."""
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

    @staticmethod
    def _register_backup_job(
        trigger: Any,
        *,
        backup_path: str | None = None,
        retention: int = 10,
        config_id: int | None = None,
    ) -> None:
        """(Re)create the single ``auto_backup`` job for *trigger*.

        ``coalesce`` collapses missed fires into one, and ``misfire_grace_time``
        lets a slightly-late fire still run instead of being dropped.
        """
        sched = SchedulerService.get_scheduler()
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")
        if config_id is not None:
            sched.add_job(
                _run_cloud_backup,
                trigger=trigger,
                id="auto_backup",
                kwargs={"config_id": config_id},
                replace_existing=True,
                coalesce=True,
                misfire_grace_time=3600,
                max_instances=1,
            )
        else:
            if not backup_path:
                raise ValueError("backup_path is required when config_id is not provided")
            sched.add_job(
                _run_backup,
                trigger=trigger,
                id="auto_backup",
                kwargs={"backup_path": backup_path, "retention": retention},
                replace_existing=True,
                coalesce=True,
                misfire_grace_time=3600,
                max_instances=1,
            )

    @staticmethod
    async def start() -> None:
        """Start the global scheduler and (re)sync reminder/backup jobs."""
        sched = SchedulerService.get_scheduler()
        if not sched.running:
            sched.start()
            logger.info("Backup scheduler started")
        # (Re)register every active reminder so they fire after a restart.
        await SchedulerService.sync_reminders()
        # Re-register the persisted backup schedule (lost on restart because
        # APScheduler's job store is in-memory).
        await SchedulerService._restore_backup_schedule()
        # Restore the recurring email-sync job (in-memory job store).
        await SchedulerService.sync_email_accounts()
        # Run a missed backup shortly after boot, mirroring reminder catch-up.
        if sched.running:
            from apscheduler.triggers.date import DateTrigger

            sched.add_job(
                SchedulerService._backup_catchup,
                trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=45)),
                id="backup_catchup",
                replace_existing=True,
            )
            # Optional first email sync shortly after boot.
            from app.core.config import settings

            if settings.EMAIL_SYNC_ON_STARTUP:
                sched.add_job(
                    _run_email_sync,
                    trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=50)),
                    id="email_sync_boot",
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                )

    @staticmethod
    async def shutdown() -> None:
        """Stop the global scheduler."""
        sched = SchedulerService.get_scheduler()
        if sched.running:
            sched.shutdown()
            logger.info("Backup scheduler stopped")

    async def schedule_backup(
        self,
        cron_expr: str,
        backup_path: str | None = None,
        retention: int = 10,
        config_id: int | None = None,
    ) -> dict[str, str | int | None]:
        """Schedule an automated backup job and persist it across restarts.

        Args:
            cron_expr: Cron expression (e.g., "0 2 * * *" for 2am daily)
            backup_path: Directory path to store backups (local mode only)
            retention: Number of backups to keep (local mode only, default 10)
            config_id: BackupConfig ID for cloud upload (e.g., Google Drive).
                       When provided, the job uses BackupService.run_backup().
        """
        sched = self.get_scheduler()
        if not sched.running:
            sched.start()
            logger.info("Backup scheduler auto-started")

        # Defence-in-depth: a local backup_path must be contained before we
        # persist it. The endpoint also checks and returns HTTP 400; this guard
        # protects non-HTTP callers (restored schedules re-fire via _run_backup).
        if config_id is None and backup_path:
            from app.core.paths import resolve_backup_path

            resolve_backup_path(backup_path)

        trigger = SchedulerService._cron_trigger(cron_expr)
        SchedulerService._register_backup_job(
            trigger, backup_path=backup_path, retention=retention, config_id=config_id
        )

        # Persist to the DB (source of truth) so the job survives restarts.
        # last_run_at on the existing row is preserved by _save_schedule.
        entry: ScheduleEntry = {"cron": cron_expr}
        if config_id is not None:
            entry["config_id"] = config_id
            await _set_config_schedule_cron(config_id, cron_expr)
        else:
            # _register_backup_job above raises ValueError if backup_path is
            # falsy when config_id is None, so it is guaranteed non-None here.
            assert backup_path is not None
            entry["backup_path"] = backup_path
            entry["retention"] = retention
        await _save_schedule(entry)

        job = sched.get_job("auto_backup")
        return {
            "job_id": "auto_backup",
            "cron": cron_expr,
            "config_id": config_id,
            "next_run": str(job.next_run_time) if job else None,
        }

    async def get_status(self) -> dict[str, bool | str | int | None]:
        """Return current scheduler status (backup + reminders)."""
        sched = self.get_scheduler()
        job = sched.get_job("auto_backup")
        reminder_jobs = [j for j in sched.get_jobs() if j.id.startswith("reminder_")]
        return {
            "running": sched.running,
            "backup_scheduled": job is not None,
            "next_run": str(job.next_run_time) if job else None,
            "reminders_scheduled": len(reminder_jobs),
        }

    async def get_active_schedule(self) -> ActiveSchedule | None:
        """Return the active schedule record, or None if none is configured."""
        return await _get_active_schedule()

    async def unschedule_backup(self) -> dict[str, bool]:
        """Remove the automated backup job and its persisted schedule."""
        sched = self.get_scheduler()
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")
        await _delete_schedule()
        await _clear_config_schedule_cron()
        _clear_legacy_schedule()  # tidy any leftover legacy file
        return {"removed": True}

    @staticmethod
    async def _restore_backup_schedule() -> None:
        """Re-register the persisted backup job after a restart.

        Source of truth is the ``backup_schedule`` DB row. If none exists but a
        legacy ``.backup-schedule.json`` is present (pre-upgrade install), migrate
        it into the DB and remove the file. No-op when nothing is active.
        """
        sched = SchedulerService.get_scheduler()
        if not sched.running:
            return

        active = await _get_active_schedule()
        if active is None:
            # One-time upgrade migration from the legacy JSON store.
            legacy = _load_legacy_schedule()
            if not legacy or not legacy.get("cron"):
                return
            await _save_schedule(legacy)
            _clear_legacy_schedule()
            active = await _get_active_schedule()
            if active is None:
                return
            logger.info(
                "Migrated backup schedule from legacy file (cron=%s)", legacy["cron"]
            )

        cron = active.cron
        config_id = active.config_id
        backup_path = active.backup_path
        retention = active.retention

        try:
            if config_id is not None:
                # Don't re-register a schedule whose config was deleted.
                from sqlalchemy import select

                from app.core.database import async_session
                from app.models.backup import BackupConfig

                async with async_session() as session:
                    still_exists = (
                        await session.execute(
                            select(BackupConfig.id).where(BackupConfig.id == int(config_id))
                        )
                    ).scalar_one_or_none()
                if still_exists is None:
                    logger.info(
                        "Persisted backup config %s no longer exists; clearing schedule",
                        config_id,
                    )
                    await _delete_schedule()
                    await _clear_config_schedule_cron()
                    return
                SchedulerService._register_backup_job(
                    SchedulerService._cron_trigger(cron), config_id=int(config_id)
                )
                logger.info(
                    "Restored cloud backup schedule (config_id=%s, cron=%s)", config_id, cron
                )
            elif backup_path:
                SchedulerService._register_backup_job(
                    SchedulerService._cron_trigger(cron),
                    backup_path=str(backup_path),
                    retention=int(retention),
                )
                logger.info("Restored local backup schedule (cron=%s, path=%s)", cron, backup_path)
            else:
                await _delete_schedule()
        except Exception:
            logger.warning("Failed to restore backup schedule", exc_info=True)

    @staticmethod
    async def _backup_catchup() -> None:
        """Run a scheduled backup that was missed while the app was offline.

        Fires once shortly after startup. If the most recent scheduled
        occurrence has no matching successful run on record (and isn't too
        stale), the backup runs immediately — so a laptop that was closed at
        2am still gets its daily backup when opened the next morning.
        """
        active = await _get_active_schedule()
        if active is None:
            return

        now_local = datetime.now()  # naive local time — schedules are local
        last_occurrence = _last_scheduled_occurrence(active.cron, now_local)
        if last_occurrence is None:
            return

        last_run: datetime | None = None
        if active.last_run_at is not None:
            lr = active.last_run_at
            # _mark_backup_run stores UTC; match the reminder catch-up pattern:
            # convert an aware value to local, treat a naive value as-is.
            last_run = lr.astimezone().replace(tzinfo=None) if lr.tzinfo else lr

        if last_run is not None and last_run >= last_occurrence:
            return  # already backed up for the most recent scheduled occurrence
        if (now_local - last_occurrence) > timedelta(hours=48):
            return  # too stale to catch up automatically

        try:
            if active.config_id is not None:
                logger.info("Running missed cloud backup (config_id=%s)", active.config_id)
                await _run_cloud_backup(active.config_id)
            elif active.backup_path:
                logger.info("Running missed local backup")
                await _run_backup(active.backup_path, active.retention)
        except Exception:
            logger.warning("Backup catch-up failed", exc_info=True)

    # ── Reminder scheduling ──────────────────────────────────────────
    # Reminders recur weekly on selected days at a fixed time-of-day.
    # Each active reminder gets its own APScheduler job (id="reminder_{id}").
    # A single fire-and-forget background task (id="reminder_catchup") runs
    # shortly after startup to deliver any reminders whose time passed while
    # the app was offline.

    @staticmethod
    async def sync_reminders() -> int:
        """Reconcile scheduled reminder jobs with the DB.

        Adds jobs for active reminders, removes jobs for deleted/inactive ones.
        Returns the number of reminder jobs currently scheduled. Safe to call
        repeatedly (idempotent via ``replace_existing=True``).
        """
        from app.models.reminder import Reminder

        sched = SchedulerService.get_scheduler()
        if not sched.running:
            return 0

        from app.core.database import async_session
        from sqlalchemy import select

        async with async_session() as session:
            reminders = (await session.execute(select(Reminder))).scalars().all()

        active_ids = {r.id for r in reminders if r.is_active}
        # Remove jobs for reminders that no longer exist or are inactive.
        for job in list(sched.get_jobs()):
            if job.id.startswith("reminder_") and job.id != "reminder_catchup":
                try:
                    rid = int(job.id.split("_", 1)[1])
                except ValueError:
                    continue
                if rid not in active_ids:
                    sched.remove_job(job.id)

        # (Re)add jobs for active reminders.
        from apscheduler.triggers.cron import CronTrigger

        for r in reminders:
            if not r.is_active:
                continue
            job_id = f"reminder_{r.id}"
            days = SchedulerService._parse_days_of_week(r.days_of_week)
            trigger = CronTrigger(
                hour=r.reminder_time.hour,
                minute=r.reminder_time.minute,
                second=r.reminder_time.second,
                day_of_week=days,
            )
            sched.add_job(
                _fire_reminder,
                trigger=trigger,
                id=job_id,
                kwargs={"reminder_id": r.id},
                replace_existing=True,
            )

        return len([j for j in sched.get_jobs() if j.id.startswith("reminder_")])

    @staticmethod
    async def unschedule_reminder(reminder_id: int) -> None:
        """Remove a single reminder's job (called on delete/deactivate)."""
        sched = SchedulerService.get_scheduler()
        job_id = f"reminder_{reminder_id}"
        if sched.get_job(job_id):
            sched.remove_job(job_id)

    @staticmethod
    def _parse_days_of_week(days_of_week: str) -> str:
        """Convert our "0=Mon..6=Sun" list to APScheduler's mon-sun names.

        APScheduler accepts comma-separated ints where 0=Monday by default,
        which matches our own convention, so this is mostly validation.
        """
        _NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        out: list[str] = []
        for part in str(days_of_week).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                idx = int(part)
            except ValueError:
                continue
            if 0 <= idx <= 6 and _NAMES[idx] not in out:
                out.append(_NAMES[idx])
        return ",".join(out) or "mon,tue,wed,thu,fri,sat,sun"

    @staticmethod
    async def schedule_catchup() -> None:
        """Deliver reminders whose time passed while offline.

        Runs once ~30s after startup. For each active reminder whose
        ``reminder_time`` is earlier than now and which did not already fire
        today (``last_fired_at``), fire it immediately.
        """
        from app.models.reminder import Reminder
        from sqlalchemy import select

        from app.core.database import async_session

        try:
            async with async_session() as session:
                reminders = (await session.execute(select(Reminder))).scalars().all()
            now = datetime.now(timezone.utc)
            for r in reminders:
                if not r.is_active:
                    continue
                due = _reminder_due_for_catchup(r, now)
                if due:
                    await _fire_reminder(r.id, mark_fired=True)
        except Exception:
            logger.warning("Reminder catch-up sweep failed", exc_info=True)

    # ── Email scheduling ─────────────────────────────────────────────
    # A single recurring 'email_sync' interval job polls every active,
    # sync-enabled account. It is (re)created whenever accounts or the sync
    # interval change (EmailAccountService._reschedule_jobs →
    # sync_email_accounts) and removed when no account remains. An optional
    # one-off 'email_sync_boot' job runs a first sync shortly after startup
    # when EMAIL_SYNC_ON_STARTUP is set.

    @staticmethod
    async def sync_email_accounts() -> int:
        """Reconcile the recurring email-sync job with the DB + settings.

        Creates the ``email_sync`` interval job when at least one active,
        sync-enabled account exists (firing every ``EMAIL_SYNC_INTERVAL_MINUTES``
        minutes), otherwise removes it. No-op (returns 0) when the scheduler
        isn't running — e.g. during tests. Idempotent via ``replace_existing``.
        """
        from sqlalchemy import select

        from app.core.config import settings
        from app.core.database import async_session
        from app.models.email_account import EmailAccount

        sched = SchedulerService.get_scheduler()
        if not sched.running:
            return 0

        async with async_session() as session:
            active = (
                (
                    await session.execute(
                        select(EmailAccount.id).where(
                            EmailAccount.is_active == True,  # noqa: E712
                            EmailAccount.sync_enabled == True,  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )

        job = sched.get_job("email_sync")
        if not active:
            if job is not None:
                sched.remove_job("email_sync")
            return 0

        interval = max(1, settings.EMAIL_SYNC_INTERVAL_MINUTES)
        sched.add_job(
            _run_email_sync,
            trigger="interval",
            minutes=interval,
            id="email_sync",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=600,
            max_instances=1,
        )
        return 1


# Guards the email sync so the one-off boot job and the recurring interval job
# (different APScheduler IDs, so per-job max_instances doesn't prevent overlap)
# can't run concurrently against the single-writer SQLite DB.
_email_sync_lock = asyncio.Lock()


async def _run_email_sync() -> None:
    """Scheduled email sync — pull new messages for all active accounts.

    Opens its own DB session (APScheduler runs outside FastAPI DI). Never
    raises; per-account failures are logged by ``EmailSyncService``.
    """
    if _email_sync_lock.locked():
        logger.info("Email sync already in progress; skipping this run")
        return
    async with _email_sync_lock:
        from app.core.database import async_session
        from app.services.email_service import EmailSyncService

        logger.info("Running scheduled email sync")
        try:
            async with async_session() as session:
                await EmailSyncService(session).sync_all_accounts()
        except Exception:
            logger.error("Scheduled email sync failed", exc_info=True)


async def _run_cloud_backup(config_id: int) -> None:
    """Execute a cloud backup job using BackupService.run_backup().

    Opens its own DB session since APScheduler runs outside FastAPI's
    dependency injection. All errors are logged — never raises.
    """
    from app.core.database import async_session
    from app.services.backup_service import BackupService

    logger.info("Running scheduled cloud backup (config_id=%d)", config_id)

    try:
        async with async_session() as session:
            svc = BackupService(session)
            snapshot = await svc.run_backup(config_id)
            logger.info(
                "Cloud backup complete: snapshot_id=%d, status=%s",
                snapshot.id,
                snapshot.status,
            )
            if snapshot.status == "completed":
                await _mark_backup_run()
    except Exception:
        logger.error("Scheduled cloud backup failed (config_id=%d)", config_id, exc_info=True)


async def _checkpoint_wal_robust(attempts: int = 5, delay: float = 0.5) -> bool:
    """Best-effort WAL checkpoint that retries while the database is busy.

    ``PRAGMA wal_checkpoint(TRUNCATE)`` returns ``(busy, log, checkpointed)``;
    ``busy != 0`` means it couldn't complete because an active reader holds the
    WAL. Retrying lets readers drain (which virtually always succeeds on an
    idle app). Returns True once the checkpoint fully completes, False if it
    stayed busy across all attempts.
    """
    from sqlalchemy import text

    from app.core.database import engine

    for attempt in range(attempts):
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                row = result.fetchone()
            if row is None or row[0] == 0:
                return True
        except Exception:
            logger.warning(
                "WAL checkpoint attempt %d/%d errored", attempt + 1, attempts, exc_info=True
            )
        await asyncio.sleep(delay)
    return False


async def _run_backup(backup_path: str, retention: int = 10) -> str:
    """Execute the backup job — creates a .tar.gz archive of DB + media."""
    from app.core.archive import add_backup_members
    from app.core.config import settings
    from app.core.paths import resolve_backup_path

    logger.info(f"Running scheduled backup to {backup_path}")

    # Constrain writes to user-owned space; blocks arbitrary-path writes from
    # the unauthenticated loopback endpoints and tampered persisted schedules.
    path = resolve_backup_path(backup_path)
    path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = path / f"lifelogr-backup-{timestamp}.tar.gz"

    db_file = settings.db_path
    media_dir = settings.MEDIA_DIR

    # Checkpoint the WAL so the main .db file is fully up to date before we
    # copy it. Retry on "busy" (an active reader holds the WAL); -wal/-shm are
    # bundled below as a safety net for the rare case it can't finish.
    if db_file.exists() and not await _checkpoint_wal_robust():
        logger.warning(
            "WAL checkpoint stayed busy; main DB may lag recent commits. "
            "Archive still includes -wal/-shm for completeness."
        )

    tmpdir = tempfile.mkdtemp()
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            add_backup_members(tar, db_file, media_dir)
        logger.info(f"Backup complete: {archive_path}")
        await _mark_backup_run()
    except Exception:
        logger.error("Backup failed", exc_info=True)
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Retention: remove oldest backups if exceeding limit
    _cleanup_old_backups(path, retention)
    return str(archive_path)


def _cleanup_old_backups(backup_dir: Path, retention: int) -> None:
    """Remove oldest backup files, keeping only the most recent `retention` count."""
    if retention <= 0:
        return
    backups = sorted(
        backup_dir.glob("*-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
    )
    if len(backups) > retention:
        for old in backups[:-retention]:
            old.unlink(missing_ok=True)
            logger.info(f"Removed old backup: {old.name}")


async def _fire_reminder(reminder_id: int, mark_fired: bool = True) -> None:
    """Deliver a single reminder via desktop notification.

    Opens its own DB session (APScheduler runs outside FastAPI DI).
    Records ``last_fired_at`` so the catch-up sweep won't re-fire the same
    day. Never raises — a scheduler job must not crash the loop.
    """
    from app.models.reminder import Reminder
    from sqlalchemy import select

    from app.core.database import async_session
    from app.services.reminder_service import ReminderService

    try:
        async with async_session() as session:
            result = await session.execute(select(Reminder).where(Reminder.id == reminder_id))
            reminder = result.scalar_one_or_none()
            if reminder is None or not reminder.is_active:
                return  # deleted or deactivated since the job was queued
            ReminderService._send_notification(
                reminder.title,
                reminder.message or "Time to write in your journal!",
            )
            if mark_fired:
                reminder.last_fired_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception:
        logger.error("Failed to fire reminder %d", reminder_id, exc_info=True)


def _reminder_due_for_catchup(reminder: Any, now_utc: datetime) -> bool:
    """True if a reminder should be fired by the offline catch-up sweep.

    A reminder is due when its scheduled time-of-day has passed for the
    current weekday (per its ``days_of_week``) and it hasn't already fired
    today (``last_fired_at``).
    """
    local_now = datetime.now()  # naive local time — reminders are local
    rtime: time = reminder.reminder_time
    # weekday: Monday=0 .. Sunday=6 — matches our days_of_week convention.
    today_idx = local_now.weekday()
    try:
        active_days = {int(d.strip()) for d in str(reminder.days_of_week).split(",") if d.strip()}
    except ValueError:
        active_days = set(range(7))
    if today_idx not in active_days:
        return False

    scheduled_today = local_now.replace(
        hour=rtime.hour, minute=rtime.minute, second=rtime.second, microsecond=0
    )
    if local_now < scheduled_today:
        return False  # still ahead of time today

    if reminder.last_fired_at is not None:
        last = reminder.last_fired_at
        # Already fired today (compare date in local time).
        last_local = last.astimezone() if last.tzinfo else last
        if last_local.date() == local_now.date():
            return False
    return True
