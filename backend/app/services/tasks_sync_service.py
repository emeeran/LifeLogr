"""Two-way Google Tasks sync.

Pull: list the account's task lists, then each list's tasks — a full listing on
the first run, and incremental thereafter via ``updatedMin`` + ``showDeleted``
(the Tasks API has no sync token, so deletions surface as tasks with
``deleted=true``). Task lists → ``TaskList``, tasks → ``Task`` (keyed by
``external_id``, ``source='google'``); deletions soft-delete the local row.

Push: local edits to ``source='google'`` tasks/lists (``updated_at > synced_at``)
are pushed back via ``tasks.update`` (no etag on this API → last-write-wins), and
completion toggles ``status``. Locally soft-deleted ``source='google'`` tasks are
DELETEd on Google, then their ``external_id`` cleared.

``source='manual'`` tasks/lists are never pushed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskList
from app.services.google_oauth import GoogleAPIClient
from app.services.google_sync_utils import local_tz, mark_synced

logger = logging.getLogger(__name__)

_TASKS_BASE = "https://tasks.googleapis.com/tasks/v1"


def _gdt_to_local(value: str | None) -> datetime | None:
    """Google RFC3339 timestamp → naive-local datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None)


def _local_to_gdt(dt: datetime) -> str:
    """Naive-local datetime → Google RFC3339 timestamp."""
    return dt.replace(tzinfo=local_tz()).isoformat()


class TasksSyncService:
    """Two-way sync between Google Tasks and ``Task``/``TaskList``."""

    def __init__(self, db: AsyncSession, account: Any, api: GoogleAPIClient) -> None:
        self.db = db
        self.account = account
        self.api = api

    async def sync(self) -> dict[str, Any]:
        if not self.account.tasks_enabled:
            return {"skipped": "tasks disabled"}
        try:
            pulled = await self._pull()
            pushed = await self._push()
            await self.db.commit()
            return {"pulled": pulled, "pushed": pushed}
        except Exception:
            await self.db.rollback()
            raise

    # ── Pull (Google → local) ────────────────────────────────────────────

    async def _pull(self) -> dict[str, int]:
        stats = {"lists": 0, "tasks": 0}
        try:
            resp = await self.api.request("GET", f"{_TASKS_BASE}/users/@me/lists")
            lists = resp.json().get("items", [])
        except Exception:
            logger.warning("Google tasklists failed", exc_info=True)
            return stats
        for glist in lists:
            glist_id = glist.get("id")
            if not glist_id:
                continue
            local_list = await self._upsert_list(glist)
            stats["lists"] += 1
            await self._sync_list(glist_id, local_list, stats)
        # Advance the updatedMin cursor (UTC RFC3339).
        self.account.tasks_sync_token = datetime.now(timezone.utc).isoformat()
        return stats

    async def _upsert_list(self, glist: dict[str, Any]) -> TaskList:
        ext_id = glist["id"]
        existing = await self.db.scalar(
            select(TaskList).where(
                TaskList.source == "google", TaskList.external_id == ext_id
            )
        )
        fields = {"name": glist.get("title") or "Google", "is_deleted": False, "deleted_at": None}
        if existing is None:
            existing = TaskList(source="google", external_id=ext_id, **fields)
            self.db.add(existing)
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
        await mark_synced(self.db,existing)
        return existing

    async def _sync_list(self, glist_id: str, local_list: TaskList, stats: dict[str, int]) -> None:
        params: dict[str, Any] = {"showDeleted": "true", "showCompleted": "true"}
        if self.account.tasks_sync_token:
            params["updatedMin"] = self.account.tasks_sync_token
        url = f"{_TASKS_BASE}/lists/{glist_id}/tasks"
        while True:
            try:
                resp = await self.api.request("GET", url, params=params)
                data = resp.json()
            except httpx.HTTPStatusError:
                logger.warning("Google tasks list %s failed", glist_id, exc_info=True)
                return
            for gtask in data.get("items", []):
                await self._apply_task(gtask, glist_id, local_list)
                stats["tasks"] += 1
            if data.get("nextPageToken"):
                params = {"pageToken": data["nextPageToken"]}
                continue
            break

    async def _apply_task(
        self, gtask: dict[str, Any], glist_id: str, local_list: TaskList
    ) -> None:
        ext_id = gtask.get("id")
        if not ext_id:
            return
        existing = await self.db.scalar(
            select(Task).where(Task.source == "google", Task.external_id == ext_id)
        )
        if gtask.get("deleted") or gtask.get("hidden"):
            if existing is not None and not existing.is_deleted:
                existing.is_deleted = True
                existing.deleted_at = datetime.now()
                await mark_synced(self.db,existing)
            return

        # Resolve parent subtask link (if the parent task is already local).
        parent_id: int | None = None
        parent_ext = gtask.get("parent")
        if parent_ext:
            parent = await self.db.scalar(
                select(Task).where(Task.source == "google", Task.external_id == parent_ext)
            )
            if parent is not None:
                parent_id = parent.id

        is_completed = gtask.get("status") == "completed"
        fields = {
            "list_id": local_list.id,
            "parent_id": parent_id,
            "title": gtask.get("title") or "(untitled)",
            "notes": gtask.get("notes"),
            "is_completed": is_completed,
            "completed_at": _gdt_to_local(gtask.get("completed")),
            "due_date": _gdt_to_local(gtask.get("due")),
            "is_deleted": False,
            "deleted_at": None,
        }
        if existing is None:
            existing = Task(source="google", external_id=ext_id, **fields)
            self.db.add(existing)
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
        await mark_synced(self.db,existing)

    # ── Push (local → Google) ────────────────────────────────────────────

    async def _glist_id_for(self, task: Task) -> str:
        """The Google list id a task belongs to (via its local TaskList)."""
        if task.list_id is None:
            return "@default"
        tl = await self.db.scalar(select(TaskList).where(TaskList.id == task.list_id))
        return (tl.external_id if tl and tl.external_id else "@default")

    async def _push(self) -> dict[str, int]:
        stats = {"updated": 0, "deleted": 0}

        # Deletions: source='google' tasks soft-deleted, external_id still set.
        for t in (
            await self.db.scalars(
                select(Task).where(
                    Task.source == "google",
                    Task.is_deleted == True,  # noqa: E712
                    Task.external_id.isnot(None),
                )
            )
        ).all():
            glist_id = await self._glist_id_for(t)
            try:
                await self.api.request(
                    "DELETE", f"{_TASKS_BASE}/lists/{glist_id}/tasks/{t.external_id}"
                )
                stats["deleted"] += 1
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 410):
                    stats["deleted"] += 1
                else:
                    logger.warning("Failed to delete Google task %s", t.external_id, exc_info=True)
            t.external_id = None

        # Edits: source='google' tasks locally changed since last sync.
        for t in (
            await self.db.scalars(
                select(Task).where(
                    Task.source == "google",
                    Task.is_deleted == False,  # noqa: E712
                    Task.external_id.isnot(None),
                    Task.synced_at.isnot(None),
                    Task.updated_at > Task.synced_at,
                )
            )
        ).all():
            glist_id = await self._glist_id_for(t)
            body = {
                "title": t.title,
                "notes": t.notes or "",
                "status": "completed" if t.is_completed else "needsAction",
                "due": _local_to_gdt(t.due_date) if t.due_date else None,
            }
            try:
                await self.api.request(
                    "PATCH", f"{_TASKS_BASE}/lists/{glist_id}/tasks/{t.external_id}", json_body=body
                )
                await mark_synced(self.db,t)
                stats["updated"] += 1
            except httpx.HTTPStatusError:
                logger.warning("Failed to push Google task %s", t.external_id, exc_info=True)
        return stats
