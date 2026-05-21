"""Backup route handlers."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile
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
async def export_local_backup(db: AsyncSession = Depends(get_db)) -> FileResponse:
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

    return FileResponse(
        path=str(archive_path),
        media_type="application/gzip",
        filename=f"diarium-backup-{timestamp}.tar.gz",
        background=lambda: shutil.rmtree(tmpdir, ignore_errors=True),
    )


@router.post("/import")
async def import_local_backup(file: UploadFile, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Import a .tar.gz archive to restore database and media files."""
    import io
    import tarfile

    content = await file.read()
    db_file_path: str = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    media_dir = settings.MEDIA_DIR

    restored: list[str] = []

    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name == "dev.db" or member.name.endswith("/dev.db"):
                # Extract database file
                source = tar.extractfile(member)
                if source:
                    Path(db_file_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(db_file_path).write_bytes(source.read())
                    restored.append("database")
            elif member.name.startswith("media"):
                # Extract media files
                source = tar.extractfile(member)
                if source and member.isfile():
                    # Strip leading "media/" to get relative path
                    rel = member.name
                    if rel.startswith("media/"):
                        rel = rel[len("media/"):]
                    elif rel.startswith("media\\"):
                        rel = rel[len("media\\"):]
                    target = media_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read())
                    if "media" not in restored:
                        restored.append("media")

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
