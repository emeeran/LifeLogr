"""SyncService — offline queue, flush, and conflict resolution."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import SyncQueue, SyncStatus


class SyncService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue(self, operation: str, entity_type: str, entity_id: int, payload: dict) -> SyncQueue:
        """Queue an operation for later sync."""
        item = SyncQueue(
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.dumps(payload),
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get_pending(self, limit: int = 100) -> list[SyncQueue]:
        """Return unsynced operations."""
        result = await self.db.execute(
            select(SyncQueue)
            .where(SyncQueue.is_synced == False)  # noqa: E712
            .order_by(SyncQueue.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_pending_count(self) -> int:
        """Count unsynced operations."""
        result = await self.db.execute(
            select(func.count()).select_from(SyncQueue)
            .where(SyncQueue.is_synced == False)  # noqa: E712
        )
        return result.scalar_one()

    async def flush(self, provider: str = "local") -> dict:
        """Mark all pending operations as synced."""
        pending = await self.get_pending()
        now = datetime.now()
        for item in pending:
            item.is_synced = True
            item.synced_at = now

        # Update sync status
        status = await self._get_or_create_status(provider)
        status.last_sync_at = now
        status.status = "idle"
        status.error_message = None

        await self.db.commit()
        return {"synced": len(pending), "provider": provider}

    async def get_status(self, provider: str = "local") -> SyncStatus:
        """Get sync status for a provider."""
        return await self._get_or_create_status(provider)

    async def _get_or_create_status(self, provider: str) -> SyncStatus:
        result = await self.db.execute(
            select(SyncStatus).where(SyncStatus.provider == provider)
        )
        status = result.scalar_one_or_none()
        if not status:
            status = SyncStatus(provider=provider)
            self.db.add(status)
            await self.db.flush()
        return status
