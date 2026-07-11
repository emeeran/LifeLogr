"""PlannerService — tasks, task lists, and recurring schedule events."""

from __future__ import annotations

import logging
from datetime import datetime

from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.models.schedule_event import ScheduleEvent
from app.models.task import Task, TaskList
from app.schemas.planner import (
    AgendaItem,
    ScheduleEventCreate,
    ScheduleEventUpdate,
    TaskCreate,
    TaskListCreate,
    TaskListUpdate,
    TaskReorderItem,
    TaskResponse,
    TaskUpdate,
)

logger = logging.getLogger(__name__)

MAX_SUBTASK_DEPTH = 1  # a top-level task may have subtasks, but subtasks cannot


class PlannerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Task lists ─────────────────────────────────────────────────────────

    async def create_list(self, data: TaskListCreate) -> TaskList:
        tl = TaskList(name=data.name, color=data.color, sort_order=data.sort_order)
        self.db.add(tl)
        await self.db.commit()
        await self.db.refresh(tl)
        return tl

    async def list_lists(self) -> list[TaskList]:
        stmt = (
            select(TaskList)
            .where(TaskList.is_deleted == False)  # noqa: E712
            .order_by(TaskList.sort_order, TaskList.name)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def update_list(self, list_id: int, data: TaskListUpdate) -> TaskList:
        tl = await self._get_list(list_id)
        for field in ("name", "color", "sort_order"):
            val = getattr(data, field)
            if val is not None:
                setattr(tl, field, val)
        await self.db.commit()
        await self.db.refresh(tl)
        return tl

    async def delete_list(self, list_id: int) -> None:
        tl = await self._get_list(list_id)
        tl.is_deleted = True
        await self.db.commit()

    # ── Tasks ──────────────────────────────────────────────────────────────

    async def create_task(self, data: TaskCreate) -> TaskResponse:
        if data.parent_id is not None:
            await self._assert_can_nest(data.parent_id)
        task = Task(
            title=data.title,
            list_id=data.list_id,
            parent_id=data.parent_id,
            notes=data.notes,
            priority=data.priority,
            due_date=data.due_date,
            sort_order=data.sort_order,
        )
        self.db.add(task)
        await self.db.commit()
        return self._task_to_response(await self._get_task(task.id))

    async def get_task(self, task_id: int) -> TaskResponse:
        return self._task_to_response(await self._get_task(task_id))

    async def list_tasks(
        self,
        list_id: int | None = None,
        overdue_only: bool = False,
        include_completed: bool = False,
    ) -> list[TaskResponse]:
        stmt = select(Task).where(
            Task.is_deleted == False,  # noqa: E712
            Task.parent_id.is_(None),  # top-level only; children eager-loaded
        )
        if not include_completed:
            stmt = stmt.where(Task.is_completed == False)  # noqa: E712
        if list_id is not None:
            stmt = stmt.where(Task.list_id == list_id)
        if overdue_only:
            now = datetime.now()
            stmt = stmt.where(Task.due_date.is_not(None), Task.due_date < now)
        stmt = stmt.order_by(Task.sort_order, Task.created_at)
        # Eagerly load 2 levels of subtasks (our max depth) so building the
        # response tree never triggers an async lazy-load after the session closes.
        stmt = stmt.options(
            selectinload(Task.children).selectinload(Task.children)
        )
        tasks = list((await self.db.execute(stmt)).scalars().all())
        return [self._task_to_response(t, include_completed=include_completed) for t in tasks]

    async def update_task(self, task_id: int, data: TaskUpdate) -> TaskResponse:
        task = await self._get_task(task_id)
        if data.parent_id is not None and data.parent_id != task.parent_id:
            await self._assert_can_nest(data.parent_id)
        for field in ("title", "list_id", "parent_id", "notes", "priority", "due_date", "sort_order"):
            val = getattr(data, field)
            if val is not None:
                setattr(task, field, val)
        await self.db.commit()
        return self._task_to_response(await self._get_task(task_id))

    async def set_completed(self, task_id: int, completed: bool) -> TaskResponse:
        task = await self._get_task(task_id)
        task.is_completed = completed
        task.completed_at = datetime.now() if completed else None
        await self.db.commit()
        return self._task_to_response(await self._get_task(task_id))

    async def delete_task(self, task_id: int) -> None:
        task = await self._get_task(task_id)
        task.is_deleted = True
        task.deleted_at = datetime.now()
        await self.db.commit()

    async def restore_task(self, task_id: int) -> TaskResponse:
        task = await self._get_task(task_id, include_deleted=True)
        task.is_deleted = False
        task.deleted_at = None
        await self.db.commit()
        return self._task_to_response(await self._get_task(task_id))

    async def reorder(self, items: list[TaskReorderItem]) -> None:
        """Batch-update sort_order (and optionally parent/list) for tasks."""
        for item in items:
            if item.new_parent_id is not None:
                await self._assert_can_nest(item.new_parent_id)
            task = await self._get_task(item.id, include_deleted=True)
            task.sort_order = item.new_sort_order
            if item.new_parent_id is not None:
                task.parent_id = item.new_parent_id
            if item.new_list_id is not None:
                task.list_id = item.new_list_id
        await self.db.commit()

    # ── Schedule events ────────────────────────────────────────────────────

    async def create_event(self, data: ScheduleEventCreate) -> ScheduleEvent:
        event = ScheduleEvent(
            title=data.title,
            description=data.description,
            location=data.location,
            start_at=data.start_at,
            end_at=data.end_at,
            all_day=data.all_day,
            rrule=data.rrule,
            timezone_name=data.timezone_name,
            color=data.color,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_event(self, event_id: int) -> ScheduleEvent:
        return await self._get_event(event_id)

    async def list_events(self, frm: datetime | None, to: datetime | None) -> list[ScheduleEvent]:
        """Raw events for editing (no expansion)."""
        stmt = select(ScheduleEvent).where(ScheduleEvent.is_deleted == False)  # noqa: E712
        if frm is not None:
            stmt = stmt.where(ScheduleEvent.start_at >= frm)
        if to is not None:
            stmt = stmt.where(ScheduleEvent.start_at <= to)
        stmt = stmt.order_by(ScheduleEvent.start_at)
        return list((await self.db.execute(stmt)).scalars().all())

    async def update_event(self, event_id: int, data: ScheduleEventUpdate) -> ScheduleEvent:
        event = await self._get_event(event_id)
        for field in (
            "title", "description", "location", "start_at", "end_at",
            "all_day", "rrule", "timezone_name", "color",
        ):
            val = getattr(data, field)
            if val is not None:
                setattr(event, field, val)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def delete_event(self, event_id: int) -> None:
        event = await self._get_event(event_id)
        event.is_deleted = True
        event.deleted_at = datetime.now()
        await self.db.commit()

    async def restore_event(self, event_id: int) -> ScheduleEvent:
        event = await self._get_event(event_id, include_deleted=True)
        event.is_deleted = False
        event.deleted_at = None
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_agenda(self, frm: datetime, to: datetime) -> list[AgendaItem]:
        """Expand recurring events into concrete occurrences within [frm, to]."""
        events = await self.list_events(frm=None, to=None)
        items: list[AgendaItem] = []
        for ev in events:
            if not ev.rrule:
                if frm <= ev.start_at <= to:
                    items.append(self._agenda_item(ev, ev.start_at, ev.end_at, False))
                continue
            occurrences = self._expand_recurrence(ev, frm, to)
            for start in occurrences:
                end = start + (ev.end_at - ev.start_at)
                items.append(self._agenda_item(ev, start, end, True))
        items.sort(key=lambda i: i.start_at)
        return items

    # ── helpers ────────────────────────────────────────────────────────────

    def _expand_recurrence(
        self, ev: ScheduleEvent, frm: datetime, to: datetime
    ) -> list[datetime]:
        """Return occurrence start datetimes in [frm, to], honoring exclusions."""
        try:
            rule = rrulestr(ev.rrule, dtstart=ev.start_at)
            occurrences = list(rule.between(frm, to, inc=True))
        except Exception:
            logger.warning("Failed to expand RRULE %r: ", ev.rrule, exc_info=True)
            return []
        excluded = {d for d in (ev.excluded_dates or [])}
        return [o for o in occurrences if o.date().isoformat() not in excluded]

    @staticmethod
    def _agenda_item(
        ev: ScheduleEvent, start: datetime, end: datetime, is_recurring: bool
    ) -> AgendaItem:
        return AgendaItem(
            event_id=ev.id,
            title=ev.title,
            description=ev.description,
            location=ev.location,
            start_at=start,
            end_at=end,
            all_day=ev.all_day,
            color=ev.color,
            is_recurring=is_recurring,
        )

    def _task_to_response(self, task: Task, include_completed: bool = True) -> TaskResponse:
        children = task.children or []
        if not include_completed:
            children = [c for c in children if not c.is_completed]
        return TaskResponse(
            id=task.id,
            parent_id=task.parent_id,
            list_id=task.list_id,
            title=task.title,
            notes=task.notes,
            is_completed=task.is_completed,
            completed_at=task.completed_at,
            priority=task.priority,
            due_date=task.due_date,
            sort_order=task.sort_order,
            is_deleted=task.is_deleted,
            created_at=task.created_at,
            updated_at=task.updated_at,
            subtasks=[self._task_to_response(c, include_completed) for c in children],
        )

    async def _assert_can_nest(self, parent_id: int) -> None:
        """Reject nesting beyond 2 levels (a subtask can't have subtasks)."""
        parent = await self._get_task(parent_id, include_deleted=True)
        if parent.parent_id is not None:
            raise ValidationError("Subtasks cannot have their own subtasks")

    async def _get_task(self, task_id: int, include_deleted: bool = False) -> Task:
        stmt = select(Task).options(
            selectinload(Task.children).selectinload(Task.children)
        ).where(Task.id == task_id)
        if not include_deleted:
            stmt = stmt.where(Task.is_deleted == False)  # noqa: E712
        task = (await self.db.execute(stmt)).scalar_one_or_none()
        if not task:
            raise NotFoundError(f"Task {task_id} not found")
        return task

    async def _get_list(self, list_id: int) -> TaskList:
        tl = (
            await self.db.execute(
                select(TaskList).where(
                    TaskList.id == list_id, TaskList.is_deleted == False  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if not tl:
            raise NotFoundError(f"Task list {list_id} not found")
        return tl

    async def _get_event(self, event_id: int, include_deleted: bool = False) -> ScheduleEvent:
        stmt = select(ScheduleEvent).where(ScheduleEvent.id == event_id)
        if not include_deleted:
            stmt = stmt.where(ScheduleEvent.is_deleted == False)  # noqa: E712
        event = (await self.db.execute(stmt)).scalar_one_or_none()
        if not event:
            raise NotFoundError(f"Event {event_id} not found")
        return event
