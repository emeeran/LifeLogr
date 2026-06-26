"""Business logic for backup configuration and execution."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import decrypt, encrypt, reencrypt
from app.models.backup import BackupConfig, BackupSnapshot
from app.schemas.backup import BackupConfigCreate

logger = logging.getLogger(__name__)


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
        from app.services.cloud_sync_service import (
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
            SyncProvider,
        )

        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))
        provider: SyncProvider | None = None

        try:
            if config.provider == "google_drive":
                google_provider = GoogleDriveProvider(creds)
                provider = google_provider
                # Try to get valid token to ensure client ID, client secret, and refresh token work
                await google_provider._ensure_valid_token()
                return True
            if config.provider == "webdav":
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                # Just do a simple listing to verify connection
                await provider.list_files("lifelogr-backup-")
                return True
            if config.provider == "onedrive":
                od = OneDriveProvider(creds)
                provider = od
                await od._ensure_valid_token()
                return True
            if config.provider == "dropbox":
                db = DropboxProvider(creds)
                provider = db
                await db._ensure_valid_token()
                return True
            raise ValueError(f"Unsupported backup provider: {config.provider}")
        finally:
            if provider is not None:
                await provider.close()

    async def _create_backup_archive(self) -> bytes:
        """Create a temporary .tar.gz backup archive in memory."""
        import io
        import tarfile
        from app.core.config import settings
        from app.core.restore import checkpoint_wal

        db_file = settings.db_path
        media_dir = settings.MEDIA_DIR

        # Checkpoint WAL to make sure database is flushed to disk
        if db_file.exists():
            await checkpoint_wal(db_file)

        archive_io = io.BytesIO()
        with tarfile.open(fileobj=archive_io, mode="w:gz") as tar:
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

        return archive_io.getvalue()

    async def run_backup(self, config_id: int) -> BackupSnapshot:
        """Perform incremental backup; transfer new/modified data since last sync."""
        from app.services.cloud_sync_service import (
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
            SyncProvider,
        )

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

        provider: SyncProvider | None = None
        try:
            creds = json.loads(decrypt(config.credentials_encrypted))
            archive_data = await self._create_backup_archive()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            filename = f"lifelogr-backup-{timestamp}.tar.gz"

            if config.provider == "google_drive":

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    # Re-encrypt at v2, upgrading any legacy v1 token on write.
                    config.credentials_encrypted = reencrypt(
                        encrypt(json.dumps(creds))
                    )

                provider = GoogleDriveProvider(creds, on_token_refresh=on_refresh)
                await provider.upload(filename, archive_data, encrypted=False)
            elif config.provider == "webdav":
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                await provider.upload(filename, archive_data, encrypted=False)
            elif config.provider in ("onedrive", "dropbox"):
                provider_cls: type[OneDriveProvider] | type[DropboxProvider] = (
                    OneDriveProvider if config.provider == "onedrive" else DropboxProvider
                )

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = provider_cls(creds, on_token_refresh=on_refresh)
                await provider.upload(filename, archive_data, encrypted=False)
            else:
                raise ValueError(f"Unsupported backup provider: {config.provider}")

            # Counts for synced items
            counts = await self.count_all()
            snapshot.entries_synced = counts["entries"]
            snapshot.media_synced = counts["media"]
            snapshot.status = "completed"
            config.last_sync_at = datetime.now(timezone.utc)
        except Exception as e:
            snapshot.status = "failed"
            snapshot.error_message = str(e)
        finally:
            if provider is not None:
                await provider.close()

        snapshot.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def restore(self, config_id: int) -> dict[str, int]:
        """Atomically replace local data with cloud backup; rollback on failure."""
        from app.services.cloud_sync_service import (
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
            SyncProvider,
        )

        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))

        import io
        import shutil
        import tarfile
        import tempfile
        from pathlib import Path
        from app.core.config import settings
        from app.core.restore import atomic_restore

        provider: SyncProvider | None = None
        try:
            if config.provider == "google_drive":

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(
                        encrypt(json.dumps(creds))
                    )

                provider = GoogleDriveProvider(creds, on_token_refresh=on_refresh)
                files = await provider.list_files("lifelogr-backup-")
                if not files:
                    raise ConflictError("No backups found in Google Drive App Data")
                latest_backup = sorted(files)[-1]
                archive_data = await provider.download(latest_backup)
            elif config.provider == "webdav":
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                files = await provider.list_files("lifelogr-backup-")
                if not files:
                    raise ConflictError("No backups found in WebDAV")
                latest_backup = sorted(files)[-1]
                archive_data = await provider.download(latest_backup)
            elif config.provider in ("onedrive", "dropbox"):
                provider_cls: type[OneDriveProvider] | type[DropboxProvider] = (
                    OneDriveProvider if config.provider == "onedrive" else DropboxProvider
                )

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = provider_cls(creds, on_token_refresh=on_refresh)
                files = await provider.list_files("lifelogr-backup-")
                if not files:
                    raise ConflictError("No cloud backups found")
                latest_backup = sorted(files)[-1]
                archive_data = await provider.download(latest_backup)
            else:
                raise ValueError(f"Unsupported backup provider: {config.provider}")

            db_file_path = settings.db_path
            media_dir = settings.MEDIA_DIR

            restored_entries = 0
            restored_media = 0

            tmpdir = tempfile.mkdtemp()
            try:
                with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as tar:
                    # Defence-in-depth: reject path traversal before extraction.
                    for member in tar.getmembers():
                        if member.name.startswith("/") or ".." in member.name:
                            raise ValueError(
                                f"Invalid archive: path traversal in '{member.name}'"
                            )
                    # `filter="data"` (PEP 706) additionally strips symlinks,
                    # hardlinks, device files and absolute/parent links — closing
                    # the symlink-escape vector the manual check above does not cover.
                    tar.extractall(tmpdir, filter="data")

                extracted_db = Path(tmpdir) / "diarium.diarium"
                if not extracted_db.exists():
                    extracted_db = Path(tmpdir) / "dev.db"
                extracted_media = Path(tmpdir) / "media"

                if extracted_db.exists():
                    restored = await atomic_restore(
                        extracted_db=extracted_db,
                        extracted_media=extracted_media if extracted_media.exists() else None,
                        live_db=db_file_path,
                        live_media=media_dir,
                    )
                    if "database" in restored:
                        counts = await self.count_all()
                        restored_entries = counts["entries"]
                    if "media" in restored:
                        counts = await self.count_all()
                        restored_media = counts["media"]
                else:
                    # No DB — just restore media if present
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
        finally:
            if provider is not None:
                await provider.close()

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
        result = await self.db.execute(
            q.order_by(BackupSnapshot.started_at.desc()).offset(offset).limit(limit)
        )
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
