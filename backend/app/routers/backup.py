"""Backup route handlers."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
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
    return {"items": snapshots, "total": total, "offset": offset, "limit": limit}


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

    from app.core.restore import checkpoint_wal

    tmpdir = tempfile.mkdtemp()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = Path(tmpdir) / f"dailybyte-backup-{timestamp}.tar.gz"

    db_file = settings.db_path
    media_dir = settings.MEDIA_DIR

    import tarfile

    # Checkpoint WAL before reading to ensure consistency
    if db_file.exists():
        await checkpoint_wal(db_file)

    with tarfile.open(archive_path, "w:gz") as tar:
        if db_file.exists():
            tar.add(str(db_file), arcname="diarium.diarium")
            # Include WAL/SHM files as belt-and-suspenders
            wal_file = db_file.with_suffix(db_file.suffix + "-wal")
            shm_file = db_file.with_suffix(db_file.suffix + "-shm")
            if wal_file.exists():
                tar.add(str(wal_file), arcname="diarium.diarium-wal")
            if shm_file.exists():
                tar.add(str(shm_file), arcname="diarium.diarium-shm")
        if media_dir.exists():
            tar.add(str(media_dir), arcname="media")

    background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

    return FileResponse(
        path=str(archive_path),
        media_type="application/gzip",
        filename=f"dailybyte-backup-{timestamp}.tar.gz",
    )


@router.post("/import")
async def import_local_backup(file: UploadFile) -> dict[str, Any]:
    """Import a .tar.gz archive to restore database and media files."""
    import io
    import tarfile

    from app.core.restore import atomic_restore

    content = await file.read()
    db_file_path: Path = settings.db_path
    media_dir = settings.MEDIA_DIR

    tmpdir = tempfile.mkdtemp()
    try:
        # Extract with path traversal protection
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid archive: path traversal in '{member.name}'",
                    )
            tar.extractall(tmpdir)

        extracted_db = Path(tmpdir) / "diarium.diarium"
        # Backward compat: accept old archives that used "dev.db"
        if not extracted_db.exists():
            extracted_db = Path(tmpdir) / "dev.db"
        extracted_media = Path(tmpdir) / "media"

        if extracted_db.exists():
            try:
                restored = await atomic_restore(
                    extracted_db=extracted_db,
                    extracted_media=extracted_media if extracted_media.exists() else None,
                    live_db=db_file_path,
                    live_media=media_dir,
                )
            except ValueError as exc:
                from fastapi import HTTPException

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
        shutil.rmtree(tmpdir, ignore_errors=True)

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
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"Backup config {config_id} not found")

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
