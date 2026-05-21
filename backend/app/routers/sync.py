"""Sync route handlers — offline queue, status, flush."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.sync import (
    CloudSyncRequest,
    CloudSyncResponse,
    SyncFlushResponse,
    SyncQueueRequest,
    SyncQueueResponse,
    SyncStatusResponse,
)
from app.services.cloud_sync_service import CloudSyncService, LocalFileProvider
from app.services.sync_service import SyncService

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/enqueue", response_model=SyncQueueResponse, status_code=201)
async def enqueue_operation(
    data: SyncQueueRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Queue an operation for later sync."""
    svc = SyncService(db)
    return await svc.enqueue(data.operation, data.entity_type, data.entity_id, data.payload)


@router.get("/pending", response_model=list[SyncQueueResponse])
async def get_pending(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get unsynced operations."""
    svc = SyncService(db)
    return await svc.get_pending(limit)


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    provider: str = Query(default="local"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get sync status for a provider."""
    svc = SyncService(db)
    status = await svc.get_status(provider)
    pending = await svc.get_pending_count()
    return SyncStatusResponse(
        provider=status.provider,
        last_sync_at=status.last_sync_at,
        status=status.status,
        pending_count=pending,
    )


@router.post("/flush", response_model=SyncFlushResponse)
async def flush_sync(
    provider: str = Query(default="local"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Mark all pending operations as synced."""
    svc = SyncService(db)
    return await svc.flush(provider)


@router.post("/cloud/push", response_model=CloudSyncResponse)
async def cloud_push(
    data: CloudSyncRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Push pending changes to cloud provider."""
    provider = LocalFileProvider()
    svc = CloudSyncService(db, provider)
    result = await svc.push(data.passphrase)
    return CloudSyncResponse(pushed=result["pushed"], provider=data.provider)


@router.post("/cloud/pull", response_model=CloudSyncResponse)
async def cloud_pull(
    data: CloudSyncRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Pull changes from cloud provider."""
    provider = LocalFileProvider()
    svc = CloudSyncService(db, provider)
    result = await svc.pull(data.passphrase)
    return CloudSyncResponse(pulled=result["pulled"], provider=data.provider)
