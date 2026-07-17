"""Backup route handlers."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.backup import (
    BackupConfigCreate,
    BackupConfigResponse,
    BackupSnapshotResponse,
    RestoreRequest,
)
from app.services.backup_service import BackupService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backup", tags=["backup"])


@router.post("/config", response_model=BackupConfigResponse, status_code=201)
async def create_backup_config(data: BackupConfigCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create or update a cloud backup configuration."""
    svc = BackupService(db)
    return await svc.create_config(data)


@router.get("/config", response_model=list[BackupConfigResponse])
async def list_backup_configs(db: AsyncSession = Depends(get_db)) -> Any:
    """List all backup configurations."""
    svc = BackupService(db)
    return await svc.get_configs()


@router.post("/config/{config_id}/test")
async def test_connection(config_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Test the cloud provider connection for a config."""
    svc = BackupService(db)
    success = await svc.test_connection(config_id)
    return {"success": success, "message": "Connection OK" if success else "Connection failed"}


@router.delete("/config/{config_id}", status_code=204)
async def delete_backup_config(config_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a backup configuration."""
    svc = BackupService(db)
    await svc.delete_config(config_id)


@router.post("/run", response_model=BackupSnapshotResponse, status_code=202)
async def run_backup(
    request: RestoreRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Trigger an incremental backup in the background."""
    svc = BackupService(db)
    return await svc.run_backup(request.config_id)


@router.post("/run-now")
async def run_configured_backup_now(
    backup_path: str | None = Query(
        None, description="Local folder — run a local backup now (no saved schedule needed)"
    ),
    retention: int = Query(10, ge=1, description="Local backups to keep"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run a backup immediately.

    With ``backup_path`` a local backup runs to that folder right away — no
    persisted schedule required, so "Run now" works before the user saves one.
    Otherwise the persisted schedule runs (a local folder via ``_run_backup`` or
    a cloud config via ``BackupService.run_backup``). Actually writes the archive
    (unlike ``/export``, which is a throwaway copy).
    """
    from app.core.paths import resolve_backup_path
    from app.services.scheduler_service import SchedulerService, _run_backup

    if backup_path:
        try:
            resolved = resolve_backup_path(backup_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        archive = await _run_backup(str(resolved), retention)
        return {"mode": "local", "path": str(resolved), "archive": archive}

    active = await SchedulerService(db).get_active_schedule()
    if active is None:
        raise HTTPException(status_code=404, detail="No backup schedule is configured")

    if active.config_id is not None:
        svc = BackupService(db)
        snapshot = await svc.run_backup(active.config_id)
        return {
            "mode": "cloud",
            "config_id": active.config_id,
            "status": snapshot.status,
            "error": snapshot.error_message,
        }

    archive = await _run_backup(active.backup_path or "", active.retention)
    return {"mode": "local", "path": active.backup_path, "archive": archive}


@router.get("/snapshots")
async def list_snapshots(
    config_id: int | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List backup snapshots with pagination."""
    svc = BackupService(db)
    snapshots, total = await svc.list_snapshots(config_id, offset, limit)
    # Serialize ORM rows via the response model — returning the raw ORM objects
    # makes pydantic v2 raise "Unable to serialize unknown type" on the response.
    return {
        "items": [BackupSnapshotResponse.model_validate(s).model_dump() for s in snapshots],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.delete("/snapshots/{snapshot_id}")
async def delete_backup_snapshot(
    snapshot_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Delete a snapshot's cloud backup file (if any) and the snapshot record."""
    svc = BackupService(db)
    return await svc.delete_backup(snapshot_id)


@router.post("/restore")
async def restore_backup(
    request: RestoreRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Restore journal data from a cloud backup."""
    svc = BackupService(db)
    result = await svc.restore(request.config_id)
    return {"success": True, **result}


@router.get("/export")
async def export_local_backup(
    background_tasks: BackgroundTasks,
) -> FileResponse:
    """Export the SQLite database and media files as a .tar.gz archive."""
    from datetime import datetime, timezone

    from app.core.archive import add_backup_members
    from app.core.restore import checkpoint_wal

    tmpdir = tempfile.mkdtemp()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = Path(tmpdir) / f"lifelogr-backup-{timestamp}.tar.gz"

    db_file = settings.db_path
    media_dir = settings.MEDIA_DIR

    import tarfile

    # Checkpoint WAL before reading to ensure consistency
    if db_file.exists():
        await checkpoint_wal(db_file)

    with tarfile.open(archive_path, "w:gz") as tar:
        add_backup_members(tar, db_file, media_dir)

    background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

    return FileResponse(
        path=str(archive_path),
        media_type="application/gzip",
        filename=f"lifelogr-backup-{timestamp}.tar.gz",
    )


@router.post("/import")
async def import_local_backup(file: UploadFile) -> dict[str, Any]:
    """Import a .tar.gz archive to restore database and media files.

    Streams the upload to a temp file with a hard size cap
    (``MAX_IMPORT_SIZE_BYTES``) so an unauthenticated loopback request can't
    exhaust memory, then extracts via the shared traversal-guarded helper and
    atomically swaps the live data.
    """
    import tarfile

    from app.core.archive import extract_tar_safely
    from app.core.restore import atomic_restore

    max_bytes = settings.MAX_IMPORT_SIZE_BYTES
    db_file_path: Path = settings.db_path
    media_dir = settings.MEDIA_DIR

    # Spool the upload to disk in 1 MiB chunks, aborting with 413 past the cap.
    # Starlette already spools UploadFile to disk past ~1 MiB, but awaiting
    # file.read() materialises the whole payload — stream it ourselves instead.
    upload = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    upload_path = Path(upload.name)
    written = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            if written + len(chunk) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Archive exceeds the {max_bytes}-byte import limit.",
                )
            upload.write(chunk)
            written += len(chunk)
        upload.flush()
        upload.close()

        extract_dir = tempfile.mkdtemp()
        try:
            with tarfile.open(upload_path, mode="r:gz") as tar:
                try:
                    extract_tar_safely(tar, extract_dir)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

            extracted_db = Path(extract_dir) / "diarium.diarium"
            # Backward compat: accept old archives that used "dev.db"
            if not extracted_db.exists():
                extracted_db = Path(extract_dir) / "dev.db"
            extracted_media = Path(extract_dir) / "media"

            if extracted_db.exists():
                try:
                    restored = await atomic_restore(
                        extracted_db=extracted_db,
                        extracted_media=extracted_media if extracted_media.exists() else None,
                        live_db=db_file_path,
                        live_media=media_dir,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            else:
                restored = []
                # No DB in archive — just restore media if present
                if extracted_media.exists():
                    if media_dir.exists():
                        shutil.rmtree(str(media_dir))
                    shutil.copytree(str(extracted_media), str(media_dir))
                    restored.append("media")
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)
    finally:
        upload.close()  # idempotent — safe if already closed after the chunk loop
        upload_path.unlink(missing_ok=True)

    return {"success": True, "restored": restored}


# ── Automated backup scheduling ────────────────────────────────────────────────


@router.post("/schedule")
async def schedule_backup(
    cron: str = Query(..., description="Cron expression (e.g., '0 2 * * *')"),
    backup_path: str | None = Query(None, description="Directory path for local backup files"),
    retention: int = Query(10, ge=1, le=100, description="Number of local backups to keep"),
    config_id: int | None = Query(
        None, description="BackupConfig ID for cloud upload (e.g., Google Drive)"
    ),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Schedule an automated backup job.

    Provide **config_id** to upload to a cloud provider (Google Drive, WebDAV),
    or **backup_path** for local filesystem backups.
    """
    from sqlalchemy import select

    from app.models.backup import BackupConfig
    from app.services.scheduler_service import SchedulerService

    # Validate config_id exists before scheduling
    if config_id is not None:
        result = await db.execute(select(BackupConfig).where(BackupConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail=f"Backup config {config_id} not found")

    # Local backups must target user-owned space (security: unauthenticated
    # loopback endpoint). SchedulerService.schedule_backup re-checks defensively.
    if backup_path and config_id is None:
        from app.core.paths import resolve_backup_path

        try:
            resolve_backup_path(backup_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    svc = SchedulerService(db)
    return await svc.schedule_backup(cron, backup_path, retention, config_id)


@router.get("/schedule/status")
async def schedule_status(db: AsyncSession = Depends(get_db)) -> Any:
    """Check the status of the backup scheduler."""
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService(db)
    return await svc.get_status()


@router.delete("/schedule")
async def unschedule_backup(db: AsyncSession = Depends(get_db)) -> Any:
    """Remove the automated backup schedule."""
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService(db)
    return await svc.unschedule_backup()


@router.post("/config/migrate-credentials")
async def migrate_credential_encryption(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upgrade all backup configs from legacy v1 to v2 (HKDF) token format.

    Idempotent: v2 tokens pass through unchanged. Returns the number of tokens
    upgraded so the v1 fallback path can be retired once this reports zero.
    """
    from app.core.security import reencrypt, token_version
    from app.models.backup import BackupConfig
    from sqlalchemy import select

    result = await db.execute(select(BackupConfig))
    configs = result.scalars().all()
    upgraded = 0
    for config in configs:
        if token_version(config.credentials_encrypted) == 1:
            config.credentials_encrypted = reencrypt(config.credentials_encrypted)
            upgraded += 1
    if upgraded:
        await db.commit()
    remaining = sum(1 for c in configs if token_version(c.credentials_encrypted) == 1)
    return {
        "checked": len(configs),
        "upgraded": upgraded,
        "remaining_v1": remaining,
    }
