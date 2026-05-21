"""Automated backup scheduling with APScheduler and optional encryption."""
from __future__ import annotations

import json
import logging
from datetime import datetime
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

    async def schedule_backup(self, cron_expr: str, backup_path: str) -> dict:
        """Schedule an automated backup job.

        Args:
            cron_expr: Cron expression (e.g., "0 2 * * *" for 2am daily)
            backup_path: Directory path to store backups
        """
        sched = self.get_scheduler()
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
        )

        # Remove existing backup job if any
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")

        sched.add_job(
            _run_backup,
            trigger=trigger,
            id="auto_backup",
            kwargs={"backup_path": backup_path},
            replace_existing=True,
        )

        return {
            "job_id": "auto_backup",
            "cron": cron_expr,
            "next_run": str(sched.get_job("auto_backup").next_run_time),
        }

    async def get_status(self) -> dict:
        """Return current scheduler status."""
        sched = self.get_scheduler()
        job = sched.get_job("auto_backup")
        return {
            "running": sched.running,
            "backup_scheduled": job is not None,
            "next_run": str(job.next_run_time) if job else None,
        }

    async def unschedule_backup(self) -> dict:
        """Remove the automated backup job."""
        sched = self.get_scheduler()
        if sched.get_job("auto_backup"):
            sched.remove_job("auto_backup")
        return {"removed": True}


async def _run_backup(backup_path: str) -> None:
    """Execute the backup job — creates a JSON export of all data."""
    from app.core.database import async_session
    from app.models.entry import Entry
    from sqlalchemy import select

    logger.info(f"Running scheduled backup to {backup_path}")

    path = Path(backup_path)
    path.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        result = await db.execute(
            select(Entry).where(Entry.is_deleted == False)  # noqa: E712
        )
        entries = list(result.scalars().all())

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = path / f"backup_{timestamp}.json"

        data = {
            "exported_at": datetime.now().isoformat(),
            "entry_count": len(entries),
            "entries": [
                {
                    "id": e.id,
                    "date": str(e.entry_date),
                    "title": e.title,
                    "body": e.body,
                    "mood": e.mood,
                    "created_at": str(e.created_at),
                }
                for e in entries
            ],
        }

        filename.write_text(json.dumps(data, indent=2))
        logger.info(f"Backup complete: {filename} ({len(entries)} entries)")
