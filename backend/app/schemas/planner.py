"""Pydantic schemas for the Planner module (tasks + schedule events)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Priority


# ── Task lists ─────────────────────────────────────────────────────────────


class TaskListCreate(BaseModel):
    name: str = Field(max_length=100)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int = 0


class TaskListUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int | None = None


class TaskListResponse(BaseModel):
    id: int
    name: str
    color: str | None
    sort_order: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Tasks ──────────────────────────────────────────────────────────────────


class TaskCreate(BaseModel):
    title: str = Field(max_length=500)
    list_id: int | None = None
    parent_id: int | None = None
    notes: str | None = None
    priority: Priority | None = None
    due_date: datetime | None = None
    sort_order: int = 0


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    list_id: int | None = None
    parent_id: int | None = None
    notes: str | None = None
    priority: Priority | None = None
    due_date: datetime | None = None
    sort_order: int | None = None


class TaskResponse(BaseModel):
    id: int
    parent_id: int | None
    list_id: int | None
    title: str
    notes: str | None
    is_completed: bool
    completed_at: datetime | None
    priority: Priority | None
    due_date: datetime | None
    sort_order: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    subtasks: list["TaskResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class TaskReorderItem(BaseModel):
    id: int
    new_sort_order: int
    new_parent_id: int | None = None
    new_list_id: int | None = None


class TaskReorderRequest(BaseModel):
    items: list[TaskReorderItem]


class TaskCompleteUpdate(BaseModel):
    completed: bool


# ── Schedule events ────────────────────────────────────────────────────────


class ScheduleEventCreate(BaseModel):
    title: str = Field(max_length=500)
    description: str | None = None
    location: str | None = Field(default=None, max_length=500)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    rrule: str | None = Field(default=None, max_length=500)
    timezone_name: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=20)


class ScheduleEventUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    location: str | None = Field(default=None, max_length=500)
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    rrule: str | None = Field(default=None, max_length=500)
    timezone_name: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=20)


class ScheduleEventResponse(BaseModel):
    id: int
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    rrule: str | None
    timezone_name: str | None
    color: str | None
    excluded_dates: list[str] | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Agenda (virtual expanded occurrences) ──────────────────────────────────


class AgendaItem(BaseModel):
    """A single visible occurrence of an event within a queried range."""

    event_id: int
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    color: str | None
    is_recurring: bool


class AgendaResponse(BaseModel):
    items: list[AgendaItem]
    total: int
    frm: datetime
    to: datetime
