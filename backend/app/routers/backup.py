"""Backup route handlers."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.backup import BackupConfigCreate, BackupConfigResponse, BackupSnapshotResponse, RestoreRequest
from app.services.backup_service import BackupService

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
async def restore_backup(request: RestoreRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Restore journal data from a cloud backup."""
    svc = BackupService(db)
    result = await svc.restore(request.config_id)
    return {"success": True, **result}


@router.get("/export")
async def export_local_backup(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Export the SQLite database and media files as a .tar.gz archive."""
    from datetime import datetime

    svc = BackupService(db)
    await svc.count_all()

    tmpdir = tempfile.mkdtemp()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = Path(tmpdir) / f"diarium-backup-{timestamp}.tar.gz"

    # Build the tar.gz from db file + media dir
    db_url: str = settings.DATABASE_URL
    db_file = db_url.replace("sqlite+aiosqlite:///", "")
    media_dir = settings.MEDIA_DIR

    import tarfile

    with tarfile.open(archive_path, "w:gz") as tar:
        if Path(db_file).exists():
            tar.add(db_file, arcname="dev.db")
        if media_dir.exists():
            tar.add(str(media_dir), arcname="media")

    background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

    return FileResponse(
        path=str(archive_path),
        media_type="application/gzip",
        filename=f"diarium-backup-{timestamp}.tar.gz",
    )


@router.post("/import")
async def import_local_backup(file: UploadFile) -> dict[str, Any]:
    """Import a .tar.gz archive to restore database and media files."""
    import io
    import tarfile

    from app.core.database import init_db, reinit_engine

    content = await file.read()
    db_file_path: str = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    media_dir = settings.MEDIA_DIR

    restored: list[str] = []

    # 1. Extract backup to temp dir first (validate before touching anything)
    tmpdir = tempfile.mkdtemp()
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            tar.extractall(tmpdir)

        # 2. If archive contains a database, swap it in
        extracted_db = Path(tmpdir) / "dev.db"
        if extracted_db.exists():
            await reinit_engine()  # disposes old engine, creates fresh one
            shutil.copy2(str(extracted_db), db_file_path)
            await init_db()  # re-create FTS triggers, seed templates
            restored.append("database")

        # 3. Extract media files
        extracted_media = Path(tmpdir) / "media"
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
    backup_path: str = Query(..., description="Directory path for backup files"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Schedule an automated backup job."""
    from app.services.scheduler_service import SchedulerService
    svc = SchedulerService(db)
    return await svc.schedule_backup(cron, backup_path)


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
