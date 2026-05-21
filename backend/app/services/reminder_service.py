"""ReminderService — CRUD and desktop notification delivery for reminders."""
from __future__ import annotations

import subprocess

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.reminder import Reminder
from app.schemas.reminder import ReminderCreate, ReminderUpdate


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
        return reminder

    async def get(self, reminder_id: int) -> Reminder:
        result = await self.db.execute(
            select(Reminder).where(Reminder.id == reminder_id)
        )
        reminder = result.scalar_one_or_none()
        if not reminder:
            raise NotFoundError(f"Reminder {reminder_id} not found")
        return reminder

    async def list_all(self) -> list[Reminder]:
        result = await self.db.execute(
            select(Reminder).order_by(Reminder.reminder_time)
        )
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
        return reminder

    async def delete(self, reminder_id: int) -> None:
        reminder = await self.get(reminder_id)
        await self.db.delete(reminder)
        await self.db.commit()

    async def test_notification(self, reminder_id: int) -> dict:
        """Send a test desktop notification for the reminder."""
        reminder = await self.get(reminder_id)
        self._send_notification(reminder.title, reminder.message or "This is a test reminder")
        return {"sent": True, "title": reminder.title}

    @staticmethod
    def _send_notification(title: str, message: str) -> None:
        """Send a desktop notification using notify-send (Linux)."""
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Diarilinux", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # notify-send not available
