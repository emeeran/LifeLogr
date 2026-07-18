"""Shared helpers for the Google Calendar/Tasks two-way sync services."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


def local_tz() -> Any:
    """The process's local timezone (for naive<->aware conversion)."""
    return datetime.now().astimezone().tzinfo


async def mark_synced(db: AsyncSession, obj: Any) -> None:
    """Persist + reload the server-generated ``updated_at``, then mirror it.

    ``synced_at == updated_at`` guarantees a just-pulled row isn't seen as
    locally changed (push picks up ``updated_at > synced_at``). Using ``refresh``
    (awaited) rather than a plain attribute read avoids the async lazy-load
    ``MissingGreenlet`` error on server-generated columns.
    """
    await db.flush()  # pending → persistent so refresh can reload it
    await db.refresh(obj)
    obj.synced_at = obj.updated_at
