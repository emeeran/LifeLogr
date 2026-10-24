"""Pydantic schemas for journaling reminders."""

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field


class ReminderCreate(BaseModel):
    """Create a new reminder."""

    title: str = Field(max_length=255)
    message: str | None = Field(default=None, max_length=500)
    reminder_time: time
    days_of_week: str = Field(
        default="1,2,3,4,5",
        max_length=20,
        description="Comma-separated day numbers, 0=Mon..6=Sun",
    )
    is_active: bool = True

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Evening journal",
                "message": "Time to write about your day!",
                "reminder_time": "21:00:00",
                "days_of_week": "0,1,2,3,4,5,6",
            }
        }
    )


class ReminderUpdate(BaseModel):
    """Update an existing reminder."""

    title: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=500)
    reminder_time: time | None = None
    days_of_week: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class ReminderResponse(BaseModel):
    """A reminder with its current state."""

    id: int
    title: str
    message: str | None
    reminder_time: time
    days_of_week: str
    is_active: bool
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
