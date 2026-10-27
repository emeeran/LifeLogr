"""Sync route handlers — offline queue, status, flush."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services.cloud_sync_service import (
    CloudSyncService,
    LocalFileProvider,
    SyncService,
    UnsupportedSyncEntityType,
)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/enqueue", response_model=SyncQueueResponse, status_code=201)
async def enqueue_operation(data: SyncQueueRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Queue an operation for later sync.

    Entity types the pull merge cannot apply (e.g. ``tag``/``media``) are
    rejected with a 422 rather than queued and silently dropped on pull.
    """
    svc = SyncService(db)
    try:
        return await svc.enqueue(data.operation, data.entity_type, data.entity_id, data.payload)
    except UnsupportedSyncEntityType as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


async def _get_provider(db: AsyncSession, provider_name: str) -> Any:
    """Load and configure the sync provider dynamically from the database.

    Delegates to ``BackupService._cloud_provider_for`` — the one construction
    path shared with the backup feature. This used to be its own fifth copy of
    the dispatch, and it had drifted: it encrypted refreshed tokens instead of
    re-encrypting them, so a legacy v1 credential was never upgraded, and an
    unknown provider escaped as a ``ValueError`` (500) instead of a 400.
    """
    import json

    from sqlalchemy import select

    from app.core.exceptions import NotFoundError
    from app.core.security import decrypt
    from app.models.backup import BackupConfig
    from app.services.backup_service import BackupService

    if provider_name in ("local", "local_file"):
        return LocalFileProvider()

    res = await db.execute(select(BackupConfig).where(BackupConfig.provider == provider_name))
    config = res.scalar_one_or_none()
    if not config:
        raise NotFoundError(f"Backup configuration for provider {provider_name} not found")

    creds = json.loads(decrypt(config.credentials_encrypted))
    return BackupService(db)._cloud_provider_for(config, creds)


@router.post("/cloud/push", response_model=CloudSyncResponse)
async def cloud_push(data: CloudSyncRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Push pending changes to cloud provider."""
    async with CloudSyncService(db, await _get_provider(db, data.provider)) as svc:
        result = await svc.push(data.passphrase)
    # Ensure any updated credentials from the provider are saved.
    await db.commit()
    return CloudSyncResponse(pushed=result["pushed"], provider=data.provider)


@router.post("/cloud/pull", response_model=CloudSyncResponse)
async def cloud_pull(data: CloudSyncRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Pull changes from cloud provider."""
    async with CloudSyncService(db, await _get_provider(db, data.provider)) as svc:
        result = await svc.pull(data.passphrase)
    # Ensure any updated credentials from the provider are saved.
    await db.commit()
    return CloudSyncResponse(pulled=result["pulled"], provider=data.provider)
