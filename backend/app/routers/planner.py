"""Planner route handlers — task lists, tasks (with subtasks), and schedule events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.planner import (
    AgendaResponse,
    ScheduleEventCreate,
    ScheduleEventResponse,
    ScheduleEventUpdate,
    TaskCompleteUpdate,
    TaskCreate,
    TaskListCreate,
    TaskListResponse,
    TaskListUpdate,
    TaskReorderRequest,
    TaskResponse,
    TaskUpdate,
)
from app.services.planner_service import PlannerService

router = APIRouter(prefix="/api/v1/planner", tags=["planner"])


# ── Task lists ─────────────────────────────────────────────────────────────


@router.get("/lists", response_model=list[TaskListResponse])
async def list_task_lists(db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.list_lists()


@router.post("/lists", response_model=TaskListResponse, status_code=201)
async def create_task_list(data: TaskListCreate, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.create_list(data)


@router.patch("/lists/{list_id}", response_model=TaskListResponse)
async def update_task_list(
    list_id: int, data: TaskListUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = PlannerService(db)
    return await svc.update_list(list_id, data)


@router.delete("/lists/{list_id}", status_code=204)
async def delete_task_list(list_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = PlannerService(db)
    await svc.delete_list(list_id)


# ── Tasks ──────────────────────────────────────────────────────────────────


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    list_id: int | None = Query(default=None),
    overdue_only: bool = Query(default=False),
    include_completed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = PlannerService(db)
    return await svc.list_tasks(
        list_id=list_id, overdue_only=overdue_only, include_completed=include_completed
    )


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.create_task(data)


@router.post("/tasks/reorder")
async def reorder_tasks(data: TaskReorderRequest, db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    svc = PlannerService(db)
    await svc.reorder(data.items)
    return {"reordered": len(data.items)}


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.get_task(task_id)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int, data: TaskUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = PlannerService(db)
    return await svc.update_task(task_id, data)


@router.patch("/tasks/{task_id}/complete", response_model=TaskResponse)
async def set_task_completed(
    task_id: int, data: TaskCompleteUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = PlannerService(db)
    return await svc.set_completed(task_id, data.completed)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = PlannerService(db)
    await svc.delete_task(task_id)


@router.post("/tasks/{task_id}/restore", response_model=TaskResponse)
async def restore_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.restore_task(task_id)


# ── Schedule events ────────────────────────────────────────────────────────


@router.get("/events", response_model=list[ScheduleEventResponse])
async def list_events(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = PlannerService(db)
    return await svc.list_events(frm=from_, to=to)


@router.get("/agenda", response_model=AgendaResponse)
async def get_agenda(
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = PlannerService(db)
    items = await svc.get_agenda(frm=from_, to=to)
    return AgendaResponse(items=items, total=len(items), frm=from_, to=to)


@router.post("/events", response_model=ScheduleEventResponse, status_code=201)
async def create_event(data: ScheduleEventCreate, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.create_event(data)


@router.get("/events/{event_id}", response_model=ScheduleEventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.get_event(event_id)


@router.patch("/events/{event_id}", response_model=ScheduleEventResponse)
async def update_event(
    event_id: int, data: ScheduleEventUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = PlannerService(db)
    return await svc.update_event(event_id, data)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = PlannerService(db)
    await svc.delete_event(event_id)


@router.post("/events/{event_id}/restore", response_model=ScheduleEventResponse)
async def restore_event(event_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = PlannerService(db)
    return await svc.restore_event(event_id)
