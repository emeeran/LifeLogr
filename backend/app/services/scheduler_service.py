"""Automated backup scheduling with APScheduler and cloud provider support."""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Any = None


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
    async def start() -> None:
        """Start the global scheduler and (re)sync reminder jobs."""
        sched = SchedulerService.get_scheduler()
        if not sched.running:
            sched.start()
            logger.info("Backup scheduler started")
        # (Re)register every active reminder so they fire after a restart.
        await SchedulerService.sync_reminders()

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
        """Schedule an automated backup job.

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
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        # Remove existing backup job if any
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")

        if config_id is not None:
            sched.add_job(
                _run_cloud_backup,
                trigger=trigger,
                id="auto_backup",
                kwargs={"config_id": config_id},
                replace_existing=True,
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
            )

        return {
            "job_id": "auto_backup",
            "cron": cron_expr,
            "config_id": config_id,
            "next_run": str(sched.get_job("auto_backup").next_run_time),
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

    async def unschedule_backup(self) -> dict[str, bool]:
        """Remove the automated backup job."""
        sched = self.get_scheduler()
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")
        return {"removed": True}

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
            reminders = (
                await session.execute(select(Reminder))
            ).scalars().all()

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
                reminders = (
                    await session.execute(select(Reminder))
                ).scalars().all()
            now = datetime.now(timezone.utc)
            for r in reminders:
                if not r.is_active:
                    continue
                due = _reminder_due_for_catchup(r, now)
                if due:
                    await _fire_reminder(r.id, mark_fired=True)
        except Exception:
            logger.warning("Reminder catch-up sweep failed", exc_info=True)


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
    except Exception:
        logger.error(
            "Scheduled cloud backup failed (config_id=%d)", config_id, exc_info=True
        )


async def _run_backup(backup_path: str, retention: int = 10) -> None:
    """Execute the backup job — creates a .tar.gz archive of DB + media."""
    from app.core.config import settings
    from app.core.database import engine
    from sqlalchemy import text

    logger.info(f"Running scheduled backup to {backup_path}")

    path = Path(backup_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = path / f"lifelogr-backup-{timestamp}.tar.gz"

    db_file = settings.db_path
    media_dir = settings.MEDIA_DIR

    # Checkpoint WAL for consistency
    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        logger.warning("WAL checkpoint failed before backup", exc_info=True)

    tmpdir = tempfile.mkdtemp()
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            if db_file.exists():
                tar.add(str(db_file), arcname="diarium.diarium")
            if media_dir.exists():
                tar.add(str(media_dir), arcname="media")
        logger.info(f"Backup complete: {archive_path}")
    except Exception:
        logger.error("Backup failed", exc_info=True)
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Retention: remove oldest backups if exceeding limit
    _cleanup_old_backups(path, retention)


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
            result = await session.execute(
                select(Reminder).where(Reminder.id == reminder_id)
            )
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
        logger.error(
            "Failed to fire reminder %d", reminder_id, exc_info=True
        )


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
