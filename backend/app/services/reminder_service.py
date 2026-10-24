"""ReminderService — CRUD and desktop notification delivery for reminders."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.reminder import Reminder
from app.schemas.reminder import ReminderCreate, ReminderUpdate

logger = logging.getLogger(__name__)

# Platforms we already warned about, so an unsupported box (or a Linux box
# without notify-send) logs one structured line instead of one per reminder.
_WARNED_PLATFORMS: set[str] = set()


class ReminderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: ReminderCreate) -> Reminder:
        reminder = Reminder(
            title=data.title,
            message=data.message,
            reminder_time=data.reminder_time,
            days_of_week=data.days_of_week,
            is_active=data.is_active,
        )
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        await self._resync_jobs()
        return reminder

    async def get(self, reminder_id: int) -> Reminder:
        result = await self.db.execute(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.scalar_one_or_none()
        if not reminder:
            raise NotFoundError(f"Reminder {reminder_id} not found")
        return reminder

    async def list_all(self) -> list[Reminder]:
        result = await self.db.execute(select(Reminder).order_by(Reminder.reminder_time))
        return list(result.scalars().all())

    async def update(self, reminder_id: int, data: ReminderUpdate) -> Reminder:
        reminder = await self.get(reminder_id)
        if data.title is not None:
            reminder.title = data.title
        if data.message is not None:
            reminder.message = data.message
        if data.reminder_time is not None:
            reminder.reminder_time = data.reminder_time
        if data.days_of_week is not None:
            reminder.days_of_week = data.days_of_week
        if data.is_active is not None:
            reminder.is_active = data.is_active
        await self.db.commit()
        await self.db.refresh(reminder)
        await self._resync_jobs()
        return reminder

    async def delete(self, reminder_id: int) -> None:
        reminder = await self.get(reminder_id)
        await self.db.delete(reminder)
        await self.db.commit()
        await self._resync_jobs()

    @staticmethod
    async def _resync_jobs() -> None:
        """Reconcile APScheduler reminder jobs with DB after a CRUD change.

        Failures (e.g. scheduler not running in tests) are non-fatal: the
        reminder is still persisted and will be picked up on next startup.
        """
        try:
            from app.services.scheduler_service import SchedulerService

            await SchedulerService.sync_reminders()
        except Exception:
            logger.debug("Reminder job resync skipped", exc_info=True)

    async def test_notification(self, reminder_id: int) -> dict[str, bool | str]:
        """Send a test desktop notification for the reminder."""
        reminder = await self.get(reminder_id)
        # Off the event loop: spawning a subprocess blocks, and this is the only
        # blocking call on the reminder path.
        await asyncio.to_thread(
            ReminderService._send_notification,
            reminder.title,
            reminder.message or "This is a test reminder",
        )
        return {"sent": True, "title": reminder.title}

    @staticmethod
    def _notification_argv(title: str, message: str) -> list[str] | None:
        """Best-effort desktop-notification command for this platform.

        Linux → ``notify-send``; macOS → ``osascript``; anything else has no
        bundled backend, so we return ``None``. ``--`` ends option parsing on
        notify-send, so a title/message starting with ``-`` (e.g. "- 09:00
        standup") is treated as text rather than a flag.
        """
        if sys.platform.startswith("linux"):
            return ["notify-send", "-a", "LifeLogr", "--", title, message]
        if sys.platform == "darwin":
            # osascript takes a script string, so quote the text for AppleScript.
            script = (
                f"display notification {json.dumps(message)} "
                f"with title {json.dumps(title)}"
            )
            return ["osascript", "-e", script]
        return None

    @classmethod
    def _send_notification(cls, title: str, message: str) -> None:
        """Spawn a desktop notification (fire-and-forget, never raises).

        Best-effort by design: a missing binary or exotic platform means the
        reminder still fired (it is recorded in the DB) but silently — except
        for one structured warning per platform, so the gap is discoverable.
        """
        argv = cls._notification_argv(title, message)
        if argv is None:
            platform = sys.platform
            if platform not in _WARNED_PLATFORMS:
                _WARNED_PLATFORMS.add(platform)
                logger.warning(
                    "No desktop notification backend for platform=%s; "
                    "reminder notifications will not be shown",
                    platform,
                )
            return
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError):
            platform = f"{sys.platform}:{argv[0]}"
            if platform not in _WARNED_PLATFORMS:
                _WARNED_PLATFORMS.add(platform)
                logger.warning(
                    "Desktop notification command %s not available on platform=%s; "
                    "reminder notification skipped",
                    argv[0],
                    sys.platform,
                )
