"""Business logic for backup configuration and execution."""
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import decrypt, encrypt
from app.models.backup import BackupConfig, BackupSnapshot
from app.schemas.backup import BackupConfigCreate


class BackupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_config(self, data: BackupConfigCreate) -> BackupConfig:
        """Encrypt and store cloud provider credentials."""
        config = BackupConfig(
            provider=data.provider,
            credentials_encrypted=encrypt(json.dumps(data.credentials)),
            schedule_cron=data.schedule_cron,
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def get_configs(self) -> list[BackupConfig]:
        """Return all backup configurations."""
        result = await self.db.execute(select(BackupConfig))
        return list(result.scalars().all())

    async def test_connection(self, config_id: int) -> bool:
        """Validate stored credentials by connecting to the provider."""
        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))

        if config.provider == "google_drive":
            from app.services.cloud_sync_service import GoogleDriveProvider
            provider = GoogleDriveProvider(creds)
            # Try to get valid token to ensure client ID, client secret, and refresh token work
            await provider._ensure_valid_token()
            return True
        elif config.provider == "webdav":
            from app.services.cloud_sync_service import NextcloudProvider
            provider = NextcloudProvider(
                base_url=creds.get("url", ""),
                username=creds.get("username", ""),
                password=creds.get("password", ""),
            )
            # Just do a simple listing to verify connection
            await provider.list_files("diarilinux-backup-")
            return True
        else:
            raise ValueError(f"Unsupported backup provider: {config.provider}")

    async def _create_backup_archive(self) -> bytes:
        """Create a temporary .tar.gz backup archive in memory."""
        import io
        import tarfile
        from pathlib import Path
        from app.core.config import settings
        from app.core.database import engine
        from sqlalchemy import text

        db_file = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        media_dir = settings.MEDIA_DIR

        # Checkpoint WAL to make sure database is flushed to disk
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:
            pass

        archive_io = io.BytesIO()
        with tarfile.open(fileobj=archive_io, mode="w:gz") as tar:
            if Path(db_file).exists():
                tar.add(db_file, arcname="dev.db")
            if media_dir.exists():
                tar.add(str(media_dir), arcname="media")
        
        return archive_io.getvalue()

    async def run_backup(self, config_id: int) -> BackupSnapshot:
        """Perform incremental backup; transfer new/modified data since last sync."""
        config = await self._get_config(config_id)
        # Check for already-running backup
        running = await self.db.execute(
            select(BackupSnapshot).where(
                BackupSnapshot.config_id == config_id, BackupSnapshot.status == "in_progress"
            )
        )
        if running.scalar_one_or_none():
            raise ConflictError("Backup already in progress")

        snapshot = BackupSnapshot(config_id=config_id, status="in_progress")
        self.db.add(snapshot)
        await self.db.flush()

        try:
            creds = json.loads(decrypt(config.credentials_encrypted))
            archive_data = await self._create_backup_archive()
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"diarilinux-backup-{timestamp}.tar.gz"

            if config.provider == "google_drive":
                from app.services.cloud_sync_service import GoogleDriveProvider
                
                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = encrypt(json.dumps(creds))
                
                provider = GoogleDriveProvider(creds, on_token_refresh=on_refresh)
                await provider.upload(filename, archive_data, encrypted=False)
            elif config.provider == "webdav":
                from app.services.cloud_sync_service import NextcloudProvider
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                await provider.upload(filename, archive_data, encrypted=False)
            else:
                raise ValueError(f"Unsupported backup provider: {config.provider}")

            # Counts for synced items
            counts = await self.count_all()
            snapshot.entries_synced = counts["entries"]
            snapshot.media_synced = counts["media"]
            snapshot.status = "completed"
            config.last_sync_at = datetime.now()
        except Exception as e:
            snapshot.status = "failed"
            snapshot.error_message = str(e)

        snapshot.completed_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def restore(self, config_id: int) -> dict[str, int]:
        """Atomically replace local data with cloud backup; rollback on failure."""
        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))

        import io
        import tarfile
        import shutil
        import tempfile
        from pathlib import Path
        from app.core.database import init_db, reinit_engine
        from app.core.config import settings

        try:
            if config.provider == "google_drive":
                from app.services.cloud_sync_service import GoogleDriveProvider
                
                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = encrypt(json.dumps(creds))
                
                provider = GoogleDriveProvider(creds, on_token_refresh=on_refresh)
                files = await provider.list_files("diarilinux-backup-")
                if not files:
                    raise ConflictError("No backups found in Google Drive App Data")
                latest_backup = sorted(files)[-1]
                archive_data = await provider.download(latest_backup)
            elif config.provider == "webdav":
                from app.services.cloud_sync_service import NextcloudProvider
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                files = await provider.list_files("diarilinux-backup-")
                if not files:
                    raise ConflictError("No backups found in WebDAV")
                latest_backup = sorted(files)[-1]
                archive_data = await provider.download(latest_backup)
            else:
                raise ValueError(f"Unsupported backup provider: {config.provider}")

            # Swap local database and media directories atomically
            db_file_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            media_dir = settings.MEDIA_DIR
            
            restored_entries = 0
            restored_media = 0

            tmpdir = tempfile.mkdtemp()
            try:
                with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name.startswith("/") or ".." in member.name:
                            raise ValueError(f"Invalid archive: path traversal in '{member.name}'")
                    tar.extractall(tmpdir)

                extracted_db = Path(tmpdir) / "dev.db"
                if extracted_db.exists():
                    await reinit_engine()
                    backup_path = db_file_path + ".pre-restore.bak"
                    if Path(db_file_path).exists():
                        shutil.copy2(db_file_path, backup_path)
                    
                    try:
                        shutil.copy2(str(extracted_db), db_file_path)
                        await init_db()
                        counts = await self.count_all()
                        restored_entries = counts["entries"]
                        Path(backup_path).unlink(missing_ok=True)
                    except Exception:
                        if Path(backup_path).exists():
                            shutil.copy2(backup_path, db_file_path)
                        Path(backup_path).unlink(missing_ok=True)
                        raise

                extracted_media = Path(tmpdir) / "media"
                if extracted_media.exists():
                    if media_dir.exists():
                        shutil.rmtree(str(media_dir))
                    shutil.copytree(str(extracted_media), str(media_dir))
                    counts = await self.count_all()
                    restored_media = counts["media"]
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

            return {"entries_restored": restored_entries, "media_restored": restored_media}
        except Exception as e:
            await self.db.rollback()
            raise ConflictError(f"Restore failed: {str(e)}")

    async def list_snapshots(
        self, config_id: int | None, offset: int, limit: int
    ) -> tuple[list[BackupSnapshot], int]:
        """Return paginated backup history."""
        q = select(BackupSnapshot)
        count_q = select(func.count()).select_from(BackupSnapshot)
        if config_id is not None:
            q = q.where(BackupSnapshot.config_id == config_id)
            count_q = count_q.where(BackupSnapshot.config_id == config_id)
        total = (await self.db.execute(count_q)).scalar_one()
        result = await self.db.execute(q.order_by(BackupSnapshot.started_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def delete_config(self, config_id: int) -> None:
        """Delete a backup configuration and its snapshots."""
        config = await self._get_config(config_id)
        await self.db.delete(config)
        await self.db.commit()

    async def count_all(self) -> dict[str, int]:
        """Count total entries and media in the database."""
        from app.models.entry import Entry
        from app.models.media import Media

        entry_count = (await self.db.execute(select(func.count()).select_from(Entry))).scalar_one()
        media_count = (await self.db.execute(select(func.count()).select_from(Media))).scalar_one()
        return {"entries": entry_count, "media": media_count}

    async def _get_config(self, config_id: int) -> BackupConfig:
        """Fetch a backup config or raise NotFoundError."""
        result = await self.db.execute(select(BackupConfig).where(BackupConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise NotFoundError(f"Backup config {config_id} not found")
        return config
