"""Reminder route handlers — CRUD and test notification."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.reminder import ReminderCreate, ReminderResponse, ReminderUpdate
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])


@router.post("", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    data: ReminderCreate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Create a new journaling reminder."""
    svc = ReminderService(db)
    return await svc.create(data)


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(db: AsyncSession = Depends(get_db)) -> Any:
    """List all reminders."""
    svc = ReminderService(db)
    return await svc.list_all()


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(reminder_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a specific reminder."""
    svc = ReminderService(db)
    return await svc.get(reminder_id)


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: int, data: ReminderUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Update a reminder."""
    svc = ReminderService(db)
    return await svc.update(reminder_id, data)


@router.delete("/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a reminder."""
    svc = ReminderService(db)
    await svc.delete(reminder_id)


@router.post("/{reminder_id}/test", response_model=dict)
async def test_notification(reminder_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Send a test desktop notification for a reminder."""
    svc = ReminderService(db)
    return await svc.test_notification(reminder_id)
