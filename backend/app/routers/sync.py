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
from app.services.cloud_sync_service import CloudSyncService, LocalFileProvider, SyncService

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/enqueue", response_model=SyncQueueResponse, status_code=201)
async def enqueue_operation(data: SyncQueueRequest, db: AsyncSession = Depends(get_db)) -> Any:
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


async def _get_provider(db: AsyncSession, provider_name: str) -> Any:
    """Load and configure the sync provider dynamically from the database."""
    import json
    from sqlalchemy import select
    from app.models.backup import BackupConfig
    from app.core.security import decrypt, encrypt
    from app.core.exceptions import NotFoundError

    if provider_name in ("local", "local_file"):
        return LocalFileProvider()

    res = await db.execute(select(BackupConfig).where(BackupConfig.provider == provider_name))
    config = res.scalar_one_or_none()
    if not config:
        raise NotFoundError(f"Backup configuration for provider {provider_name} not found")

    creds = json.loads(decrypt(config.credentials_encrypted))

    if provider_name == "google_drive":
        from app.services.cloud_sync_service import GoogleDriveProvider

        async def on_refresh(new_access_token: str, new_expiry: str) -> None:
            creds["access_token"] = new_access_token
            creds["token_expiry"] = new_expiry
            config.credentials_encrypted = encrypt(json.dumps(creds))
            await db.flush()

        return GoogleDriveProvider(creds, on_token_refresh=on_refresh)
    elif provider_name == "webdav":
        from app.services.cloud_sync_service import NextcloudProvider

        return NextcloudProvider(
            base_url=creds.get("url", ""),
            username=creds.get("username", ""),
            password=creds.get("password", ""),
        )
    elif provider_name == "onedrive":
        from app.services.cloud_sync_service import OneDriveProvider

        async def on_refresh_od(new_access_token: str, new_expiry: str) -> None:
            creds["access_token"] = new_access_token
            creds["token_expiry"] = new_expiry
            config.credentials_encrypted = encrypt(json.dumps(creds))
            await db.flush()

        return OneDriveProvider(creds, on_token_refresh=on_refresh_od)
    elif provider_name == "dropbox":
        from app.services.cloud_sync_service import DropboxProvider

        async def on_refresh_db(new_access_token: str, new_expiry: str) -> None:
            creds["access_token"] = new_access_token
            creds["token_expiry"] = new_expiry
            config.credentials_encrypted = encrypt(json.dumps(creds))
            await db.flush()

        return DropboxProvider(creds, on_token_refresh=on_refresh_db)
    else:
        raise ValueError(f"Unsupported cloud sync provider: {provider_name}")


@router.post("/cloud/push", response_model=CloudSyncResponse)
async def cloud_push(data: CloudSyncRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Push pending changes to cloud provider."""
    provider = await _get_provider(db, data.provider)
    svc = CloudSyncService(db, provider)
    result = await svc.push(data.passphrase)
    # Ensure any updated credentials from provider are saved
    await db.commit()
    return CloudSyncResponse(pushed=result["pushed"], provider=data.provider)


@router.post("/cloud/pull", response_model=CloudSyncResponse)
async def cloud_pull(data: CloudSyncRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Pull changes from cloud provider."""
    provider = await _get_provider(db, data.provider)
    svc = CloudSyncService(db, provider)
    result = await svc.pull(data.passphrase)
    # Ensure any updated credentials from provider are saved
    await db.commit()
    return CloudSyncResponse(pulled=result["pulled"], provider=data.provider)
