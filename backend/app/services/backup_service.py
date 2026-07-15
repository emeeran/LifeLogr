"""Business logic for backup configuration and execution."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import decrypt, encrypt, reencrypt
from app.models.backup import BackupConfig, BackupSnapshot
from app.schemas.backup import BackupConfigCreate

if TYPE_CHECKING:
    from app.services.cloud_sync_service import SyncProvider

logger = logging.getLogger(__name__)


class BackupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_config(self, data: BackupConfigCreate) -> BackupConfig:
        """Encrypt and store cloud provider credentials."""
        config = BackupConfig(
            provider=data.provider,
            label=data.label,
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
            BoxProvider,
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
            if config.provider == "box":
                provider = BoxProvider(creds)
                await provider.list_files("lifelogr-backup-")
                return True
            raise ValueError(f"Unsupported backup provider: {config.provider}")
        finally:
            if provider is not None:
                await provider.close()

    async def _build_backup_archive(self) -> Path:
        """Build the .tar.gz backup on disk (not in memory); return its path.

        Writing to a temp file avoids buffering the entire — potentially
        multi-GB — archive in RAM: tarfile streams source files straight to
        disk rather than into a ``BytesIO``. The caller must ``unlink`` the
        returned path (``run_backup`` does so in a ``finally``).
        """
        import os
        import tarfile
        import tempfile

        from sqlalchemy import text

        from app.core.archive import add_backup_members
        from app.core.config import settings

        db_file = settings.db_path
        media_dir = settings.MEDIA_DIR

        # Checkpoint the WAL on the session's OWN connection (best-effort).
        # We must not open a second pooled connection here: SQLite's engine pool
        # is size 1, and this method runs inside a request that already holds
        # the one connection via self.db — asking the engine for another would
        # deadlock ("QueuePool limit ... reached"). Running the checkpoint on
        # the session also sidesteps checkpoint_wal()'s busy-raise: a "busy"
        # result just means it couldn't fully TRUNCATE (an open txn on this
        # connection holds a snapshot); committed frames still flush, and
        # -wal/-shm are bundled below so the archive is complete regardless.
        if db_file.exists():
            try:
                await self.db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            except Exception:
                logger.warning("WAL checkpoint before backup failed", exc_info=True)

        fd, archive_name = tempfile.mkstemp(suffix=".tar.gz", dir=str(settings.DATA_DIR))
        os.close(fd)
        with tarfile.open(archive_name, "w:gz") as tar:
            add_backup_members(tar, db_file, media_dir)
        return Path(archive_name)

    async def run_backup(self, config_id: int) -> BackupSnapshot:
        """Perform incremental backup; transfer new/modified data since last sync."""
        from app.services.cloud_sync_service import (
            BoxProvider,
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
            SyncProvider,
        )

        config = await self._get_config(config_id)
        # Reclaim snapshots left "in_progress" by a crashed/interrupted previous
        # run. We commit the in_progress row before the upload, so a crash
        # mid-upload would otherwise block all future backups (including the
        # daily job) forever. Anything older than 5 min is treated as stale.
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
        stale = await self.db.execute(
            select(BackupSnapshot).where(
                BackupSnapshot.config_id == config_id,
                BackupSnapshot.status == "in_progress",
                BackupSnapshot.started_at < stale_cutoff,
            )
        )
        stale_rows = stale.scalars().all()
        for old in stale_rows:
            old.status = "failed"
            old.error_message = "Interrupted: previous run did not complete"
            old.completed_at = datetime.now(timezone.utc)
        if stale_rows:
            await self.db.commit()

        # Block only genuinely-running (recent) backups.
        running = await self.db.execute(
            select(BackupSnapshot).where(
                BackupSnapshot.config_id == config_id, BackupSnapshot.status == "in_progress"
            )
        )
        if running.scalar_one_or_none():
            raise ConflictError("Backup already in progress")

        snapshot = BackupSnapshot(config_id=config_id, status="in_progress")
        self.db.add(snapshot)
        # Commit the in_progress row up front so we don't hold a write
        # transaction (and SQLite's single-writer lock) open across the slow
        # cloud upload. Holding it caused "database table is locked" on the
        # post-upload count, marking otherwise-successful backups as failed.
        await self.db.commit()
        await self.db.refresh(snapshot)

        provider: SyncProvider | None = None
        archive_path: Path | None = None
        try:
            creds = json.loads(decrypt(config.credentials_encrypted))
            archive_path = await self._build_backup_archive()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            filename = f"lifelogr-backup-{timestamp}.tar.gz"

            if config.provider == "google_drive":

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    # Re-encrypt at v2, upgrading any legacy v1 token on write.
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = GoogleDriveProvider(creds, on_token_refresh=on_refresh)
                # Best-effort: move any older hidden (App Data) backups into the
                # visible folder. Never let migration failure abort the backup.
                try:
                    await provider.migrate_appdata_backups()
                except Exception:
                    logger.warning("Google Drive App Data migration skipped", exc_info=True)
                await provider.upload_file(filename, str(archive_path), encrypted=False)
                if getattr(provider, "last_location", "folder") == "appdata":
                    # Token lacks drive.file — backup succeeded but landed in the
                    # hidden App Data folder. Keep status=completed; surface how
                    # to get the visible folder.
                    snapshot.error_message = (
                        "Backed up to hidden Google App Data — the connected "
                        "token lacks the 'drive.file' scope. Revoke the app at "
                        "myaccount.google.com/permissions and re-link to use the "
                        "visible 'LifeLogr Backups' folder."
                    )
            elif config.provider == "webdav":
                provider = NextcloudProvider(
                    base_url=creds.get("url", ""),
                    username=creds.get("username", ""),
                    password=creds.get("password", ""),
                )
                await provider.upload_file(filename, str(archive_path), encrypted=False)
            elif config.provider in ("onedrive", "dropbox"):
                provider_cls: type[OneDriveProvider] | type[DropboxProvider] = (
                    OneDriveProvider if config.provider == "onedrive" else DropboxProvider
                )

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = provider_cls(creds, on_token_refresh=on_refresh)
                await provider.upload_file(filename, str(archive_path), encrypted=False)
            elif config.provider == "box":

                async def on_refresh_box(
                    new_access_token: str, new_refresh_token: str, new_expiry: str
                ) -> None:
                    creds["access_token"] = new_access_token
                    creds["refresh_token"] = new_refresh_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = BoxProvider(creds, on_token_refresh=on_refresh_box)
                await provider.upload_file(filename, str(archive_path), encrypted=False)
            else:
                raise ValueError(f"Unsupported backup provider: {config.provider}")

            # Remember the uploaded filename so this snapshot can be deleted
            # from cloud storage later.
            snapshot.backup_filename = filename

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
            if archive_path is not None:
                Path(archive_path).unlink(missing_ok=True)

        snapshot.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    def _cloud_provider_for(self, config: BackupConfig, creds: dict[str, str]) -> SyncProvider:
        """Instantiate the cloud provider for *config* with a refresh callback.

        Centralised so provider construction stays consistent; used by
        ``delete_backup`` (run_backup keeps its own inline dispatch).
        """
        from app.services.cloud_sync_service import (
            BoxProvider,
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
        )

        if config.provider == "google_drive":

            async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                creds["access_token"] = new_access_token
                creds["token_expiry"] = new_expiry
                config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

            return GoogleDriveProvider(creds, on_token_refresh=on_refresh)

        if config.provider == "webdav":
            return NextcloudProvider(
                base_url=creds.get("url", ""),
                username=creds.get("username", ""),
                password=creds.get("password", ""),
            )

        if config.provider in ("onedrive", "dropbox"):

            async def on_refresh_od(new_access_token: str, new_expiry: str) -> None:
                creds["access_token"] = new_access_token
                creds["token_expiry"] = new_expiry
                config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

            cls = OneDriveProvider if config.provider == "onedrive" else DropboxProvider
            return cls(creds, on_token_refresh=on_refresh_od)

        if config.provider == "box":

            async def on_refresh_box(
                new_access_token: str, new_refresh_token: str, new_expiry: str
            ) -> None:
                creds["access_token"] = new_access_token
                creds["refresh_token"] = new_refresh_token
                creds["token_expiry"] = new_expiry
                config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

            return BoxProvider(creds, on_token_refresh=on_refresh_box)

        raise ValueError(f"Unsupported backup provider: {config.provider}")

    async def delete_backup(self, snapshot_id: int) -> dict[str, object]:
        """Delete a snapshot's cloud backup file (if any) and the snapshot record.

        Old snapshots without a stored filename just have their record removed.
        """
        snap = await self.db.get(BackupSnapshot, snapshot_id)
        if snap is None:
            raise NotFoundError(f"Backup snapshot {snapshot_id} not found")

        remote_deleted = False
        filename = snap.backup_filename
        if filename:
            config = await self._get_config(snap.config_id)
            creds = json.loads(decrypt(config.credentials_encrypted))
            provider = self._cloud_provider_for(config, creds)
            try:
                await provider.delete(filename)
                remote_deleted = True
            finally:
                await provider.close()

        await self.db.delete(snap)
        await self.db.commit()
        return {
            "deleted": True,
            "remote_file_deleted": remote_deleted,
            "filename": filename,
        }

    async def restore(self, config_id: int) -> dict[str, int]:
        """Atomically replace local data with cloud backup; rollback on failure."""
        from app.services.cloud_sync_service import (
            BoxProvider,
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
        from app.core.archive import extract_tar_safely
        from app.core.config import settings
        from app.core.restore import atomic_restore

        provider: SyncProvider | None = None
        try:
            if config.provider == "google_drive":

                async def on_refresh(new_access_token: str, new_expiry: str) -> None:
                    creds["access_token"] = new_access_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

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
            elif config.provider == "box":

                async def on_refresh_box(
                    new_access_token: str, new_refresh_token: str, new_expiry: str
                ) -> None:
                    creds["access_token"] = new_access_token
                    creds["refresh_token"] = new_refresh_token
                    creds["token_expiry"] = new_expiry
                    config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))

                provider = BoxProvider(creds, on_token_refresh=on_refresh_box)
                files = await provider.list_files("lifelogr-backup-")
                if not files:
                    raise ConflictError("No backups found in Box")
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
                    # Shared traversal + symlink guard (see app.core.archive).
                    extract_tar_safely(tar, tmpdir)

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
                        session=self.db,
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
        # Delete child snapshots first. The snapshots' config_id is NOT NULL and
        # the relationship has no ORM cascade, so leaving it to SQLAlchemy's
        # default would null the FK and hit an IntegrityError.
        await self.db.execute(delete(BackupSnapshot).where(BackupSnapshot.config_id == config_id))
        await self.db.delete(config)
        await self.db.commit()

    async def count_all(self) -> dict[str, int]:
        """Count total entries, media, and notes in the database."""
        from app.models.entry import Entry
        from app.models.media import Media
        from app.models.note import Note

        entry_count = (await self.db.execute(select(func.count()).select_from(Entry))).scalar_one()
        media_count = (await self.db.execute(select(func.count()).select_from(Media))).scalar_one()
        note_count = (await self.db.execute(select(func.count()).select_from(Note))).scalar_one()
        return {"entries": entry_count, "media": media_count, "notes": note_count}

    async def _get_config(self, config_id: int) -> BackupConfig:
        """Fetch a backup config or raise NotFoundError."""
        result = await self.db.execute(select(BackupConfig).where(BackupConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise NotFoundError(f"Backup config {config_id} not found")
        return config
