"""Automated backup scheduling with APScheduler and optional encryption."""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: "AsyncIOScheduler | None" = None


class SchedulerService:
    """Manages automated backup scheduling."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def get_scheduler() -> "AsyncIOScheduler":
        global _scheduler
        if _scheduler is None:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            _scheduler = AsyncIOScheduler()
        return _scheduler

    @staticmethod
    async def start() -> None:
        """Start the global scheduler."""
        sched = SchedulerService.get_scheduler()
        if not sched.running:
            sched.start()
            logger.info("Backup scheduler started")

    @staticmethod
    async def shutdown() -> None:
        """Stop the global scheduler."""
        sched = SchedulerService.get_scheduler()
        if sched.running:
            sched.shutdown()
            logger.info("Backup scheduler stopped")

    async def schedule_backup(
        self, cron_expr: str, backup_path: str, retention: int = 10
    ) -> dict[str, str]:
        """Schedule an automated backup job.

        Args:
            cron_expr: Cron expression (e.g., "0 2 * * *" for 2am daily)
            backup_path: Directory path to store backups
            retention: Number of backups to keep (default 10)
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
            "next_run": str(sched.get_job("auto_backup").next_run_time),
        }

    async def get_status(self) -> dict[str, bool | str | None]:
        """Return current scheduler status."""
        sched = self.get_scheduler()
        job = sched.get_job("auto_backup")
        return {
            "running": sched.running,
            "backup_scheduled": job is not None,
            "next_run": str(job.next_run_time) if job else None,
        }

    async def unschedule_backup(self) -> dict[str, bool]:
        """Remove the automated backup job."""
        sched = self.get_scheduler()
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")
        return {"removed": True}


async def _run_backup(backup_path: str, retention: int = 10) -> None:
    """Execute the backup job — creates a .tar.gz archive of DB + media."""
    from app.core.config import settings
    from app.core.database import engine
    from sqlalchemy import text

    logger.info(f"Running scheduled backup to {backup_path}")

    path = Path(backup_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = path / f"dailybyte-backup-{timestamp}.tar.gz"

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
    backups = sorted(backup_dir.glob("dailybyte-backup-*.tar.gz"), key=lambda p: p.stat().st_mtime)
    if len(backups) > retention:
        for old in backups[:-retention]:
            old.unlink(missing_ok=True)
            logger.info(f"Removed old backup: {old.name}")
