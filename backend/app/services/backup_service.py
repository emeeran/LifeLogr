"""Business logic for backup configuration and execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import decrypt, encrypt, reencrypt
from app.models.backup import BackupConfig, BackupSnapshot
from app.schemas.backup import BackupConfigCreate

if TYPE_CHECKING:
    from app.services.cloud_sync_service import SyncProvider

logger = logging.getLogger(__name__)

# Every provider stores archives under this prefix (run_backup, restore, and
# the retention prune all filter on it).
CLOUD_BACKUP_PREFIX = "lifelogr-backup-"

# How many cloud archives to keep per config. The local-schedule equivalent
# (``BackupSchedule.retention``) is user-configurable; cloud mode has no such
# field yet, so this is a module constant with an environment override — the
# core ``Settings`` class is deliberately not extended here.
DEFAULT_CLOUD_BACKUP_RETENTION = 14


class BackupProviderError(Exception):
    """A cloud provider/network/auth failure during a backup operation (→ 502)."""


def cloud_backup_retention() -> int:
    """Configured cloud retention count (positive; bad values fall back)."""
    raw = os.environ.get("BACKUP_CLOUD_RETENTION", "").strip()
    if not raw:
        return DEFAULT_CLOUD_BACKUP_RETENTION
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer BACKUP_CLOUD_RETENTION=%r", raw)
        return DEFAULT_CLOUD_BACKUP_RETENTION
    if value <= 0:
        logger.warning("Ignoring non-positive BACKUP_CLOUD_RETENTION=%r", raw)
        return DEFAULT_CLOUD_BACKUP_RETENTION
    return value


def select_stale_backups(files: Iterable[str], keep_name: str, retention: int) -> list[str]:
    """Cloud archives to delete: all but the newest *retention* (by name).

    Archive names embed a fixed-width UTC timestamp, so name order is
    chronological. *keep_name* (the archive just uploaded) counts toward
    retention even if the provider's listing lags and doesn't show it yet.
    """
    if retention <= 0:
        return []
    ordered = sorted(set(files) | {keep_name})
    return ordered[: max(0, len(ordered) - retention)]


async def _download_backup_archive(provider: SyncProvider, remote_name: str, dest: Path) -> None:
    """Stream *remote_name* into *dest* via the provider's file download.

    ``download_to_file`` is the streaming path — a multi-gigabyte archive must
    never be held in RAM. The bytes-based ``download`` is the fallback for
    providers that only offer it. The lookup is on the *class* because a
    dynamically-built provider (e.g. a bare test double) fabricates attributes
    on the instance, which would otherwise look implemented but write nothing.
    """
    if callable(getattr(type(provider), "download_to_file", None)):
        await provider.download_to_file(remote_name, str(dest))
        return
    dest.write_bytes(await provider.download(remote_name))


async def _count_all_fresh() -> dict[str, int]:
    """Count entries/media/notes on a brand-new session.

    ``atomic_restore`` disposes and rebuilds the engine, which strands any
    session it was handed on a dead engine — running the post-restore count on
    the request's old session raised PendingRollbackError and turned successful
    restores into misleading "Restore failed" 409s.
    """
    from app.core.database import async_session

    async with async_session() as session:
        return await BackupService(session).count_all()


def _classify_restore_error(exc: Exception) -> Exception:
    """Map an unexpected restore failure onto its HTTP-facing exception type.

    Already-classified errors pass through untouched; provider/network faults
    become ``BackupProviderError`` (502), bad-archive/DB input becomes
    ``ValidationError`` (400), and anything else propagates as-is (500).
    """
    if isinstance(exc, (ConflictError, ValidationError, BackupProviderError)):
        return exc
    if isinstance(exc, httpx.HTTPError):
        return BackupProviderError(f"Cloud provider request failed: {exc}")
    if isinstance(exc, ValueError):
        return ValidationError(str(exc))
    return exc


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
        """Validate stored credentials by connecting to the provider.

        OAuth providers are verified with an explicit token refresh (their
        ``list_files`` swallows per-space errors, so a bad token could pass
        unnoticed); WebDAV/Box are verified with a real listing.
        """
        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))
        provider = self._cloud_provider_for(config, creds)

        try:
            ensure_token = getattr(provider, "_ensure_valid_token", None)
            if callable(ensure_token):
                await ensure_token()
            else:
                await provider.list_files(CLOUD_BACKUP_PREFIX)
            return True
        finally:
            await provider.close()

    async def _build_backup_archive(self) -> Path:
        """Build the .tar.gz backup on disk (not in memory); return its path.

        Writing to a temp file avoids buffering the entire — potentially
        multi-GB — archive in RAM: tarfile streams source files straight to
        disk rather than into a ``BytesIO``. The caller must ``unlink`` the
        returned path (``run_backup`` does so in a ``finally``).
        """
        import tarfile

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

        # Gzipping the whole DB + media is synchronous file I/O — run it off the
        # event loop so a backup doesn't stall other requests (e.g. /health).
        def _pack() -> None:
            with tarfile.open(archive_name, "w:gz") as tar:
                add_backup_members(tar, db_file, media_dir)

        await asyncio.to_thread(_pack)
        return Path(archive_name)

    async def _reclaim_stale_snapshots(self, config_id: int) -> None:
        """Fail snapshots left ``in_progress`` by a crashed earlier run.

        Single atomic UPDATE: anything older than 5 minutes is treated as
        abandoned. We commit the in_progress row before the upload, so a crash
        mid-upload would otherwise block all future backups (including the
        daily job) forever.
        """
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
        await self.db.execute(
            update(BackupSnapshot)
            .where(
                BackupSnapshot.config_id == config_id,
                BackupSnapshot.status == "in_progress",
                BackupSnapshot.started_at < stale_cutoff,
            )
            .values(
                status="failed",
                error_message="Interrupted: previous run did not complete",
                completed_at=datetime.now(timezone.utc),
            )
        )

    async def _begin_snapshot(self, config_id: int) -> BackupSnapshot:
        """Atomically claim the single in-progress slot for *config_id*.

        A check-then-insert is not atomic across processes — two workers can
        both see "nothing running" and both insert. One statement inserts the
        claim only when no open snapshot exists, so ``rowcount`` decides who
        won; SQLite serialises writers, so the guard and the insert share a
        write lock. No schema change (extra unique index) is required.
        """
        await self._reclaim_stale_snapshots(config_id)
        claimed = await self.db.execute(
            text(
                """
                INSERT INTO backup_snapshots (config_id, status, entries_synced, media_synced)
                SELECT :config_id, 'in_progress', 0, 0
                WHERE NOT EXISTS (
                    SELECT 1 FROM backup_snapshots
                    WHERE config_id = :config_id AND status = 'in_progress'
                )
                """
            ),
            {"config_id": config_id},
        )
        if getattr(claimed, "rowcount", 0) != 1:  # noqa: B009 — CursorResult at runtime
            raise ConflictError("Backup already in progress")

        # Commit the in_progress row up front so we don't hold a write
        # transaction (and SQLite's single-writer lock) open across the slow
        # cloud upload. Holding it caused "database table is locked" on the
        # post-upload count, marking otherwise-successful backups as failed.
        await self.db.commit()

        row = await self.db.execute(
            select(BackupSnapshot).where(
                BackupSnapshot.config_id == config_id, BackupSnapshot.status == "in_progress"
            )
        )
        snapshot = row.scalar_one()
        await self.db.refresh(snapshot)
        return snapshot

    async def run_backup(self, config_id: int) -> BackupSnapshot:
        """Back up the DB + media to the configured cloud provider.

        Builds the archive on disk, streams it up, then prunes the provider to
        the cloud retention count. A provider failure is recorded on the
        snapshot (status=failed) rather than raised — the caller gets the row.
        """
        from app.services.cloud_sync_service import GoogleDriveProvider

        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))
        # Construct (and validate the provider name) before claiming the slot,
        # so an unsupported provider is a 400 rather than a recorded failure.
        provider = self._cloud_provider_for(config, creds)
        snapshot = await self._begin_snapshot(config_id)

        archive_path: Path | None = None
        try:
            archive_path = await self._build_backup_archive()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            filename = f"{CLOUD_BACKUP_PREFIX}{timestamp}.tar.gz"

            if isinstance(provider, GoogleDriveProvider):
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

            # Retention: drop the oldest cloud copies beyond the configured count.
            await self._prune_cloud_backups(provider, filename)

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
            await provider.close()
            if archive_path is not None:
                Path(archive_path).unlink(missing_ok=True)

        snapshot.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def _prune_cloud_backups(self, provider: SyncProvider, keep_name: str) -> int:
        """Delete the oldest cloud archives beyond the retention count.

        Best-effort: a failed listing or delete never fails the backup that
        just succeeded.
        """
        retention = cloud_backup_retention()
        try:
            files = await provider.list_files(CLOUD_BACKUP_PREFIX)
        except Exception:
            logger.warning(
                "Cloud backup retention: could not list remote backups", exc_info=True
            )
            return 0
        deleted = 0
        for name in select_stale_backups(files, keep_name, retention):
            try:
                await provider.delete(name)
                deleted += 1
            except Exception:
                logger.warning("Could not delete old cloud backup %s", name, exc_info=True)
        if deleted:
            logger.info("Pruned %d cloud backup(s) beyond retention=%d", deleted, retention)
        return deleted

    def _cloud_provider_for(self, config: BackupConfig, creds: dict[str, str]) -> SyncProvider:
        """Instantiate the cloud provider for *config* with a refresh callback.

        The single construction path for every cloud operation (test, run,
        restore, delete, and the /sync endpoints) — previously five near-copies
        that had drifted (the sync copy encrypted instead of re-encrypting, so
        legacy v1 tokens were never upgraded). A refresh persists the rotated
        token immediately at v2; the commit is best-effort so a refresh firing
        on a session whose engine is already gone can't fail the operation.
        """
        from app.services.cloud_sync_service import (
            BoxProvider,
            DropboxProvider,
            GoogleDriveProvider,
            NextcloudProvider,
            OneDriveProvider,
        )

        async def on_refresh(new_access_token: str, new_expiry: str) -> None:
            creds["access_token"] = new_access_token
            creds["token_expiry"] = new_expiry
            # Re-encrypt at v2, upgrading any legacy v1 token on write.
            config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))
            await self._commit_quietly()

        async def on_refresh_box(
            new_access_token: str, new_refresh_token: str, new_expiry: str
        ) -> None:
            creds["access_token"] = new_access_token
            creds["refresh_token"] = new_refresh_token  # Box rotates it every refresh
            creds["token_expiry"] = new_expiry
            config.credentials_encrypted = reencrypt(encrypt(json.dumps(creds)))
            await self._commit_quietly()

        if config.provider == "google_drive":
            return GoogleDriveProvider(creds, on_token_refresh=on_refresh)

        if config.provider == "webdav":
            return NextcloudProvider(
                base_url=creds.get("url", ""),
                username=creds.get("username", ""),
                password=creds.get("password", ""),
            )

        if config.provider in ("onedrive", "dropbox"):
            cls = OneDriveProvider if config.provider == "onedrive" else DropboxProvider
            return cls(creds, on_token_refresh=on_refresh)

        if config.provider == "box":
            return BoxProvider(creds, on_token_refresh=on_refresh_box)

        raise ValidationError(f"Unsupported backup provider: {config.provider}")

    async def _commit_quietly(self) -> None:
        """Commit the rotated credentials if the session is still usable."""
        try:
            await self.db.commit()
        except Exception:
            logger.warning("Could not persist refreshed provider token", exc_info=True)

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
        """Atomically replace local data with the newest cloud backup.

        The archive is streamed to a temp file (never buffered whole in RAM),
        extracted with the shared traversal guard, then swapped in by
        ``atomic_restore``. Failures keep their cause and are classified by
        ``_classify_restore_error`` so the router can return the right status:
        409 nothing to restore, 400 bad archive/DB, 502 provider/network, 500
        anything genuinely unexpected.
        """
        from app.core.archive import extract_archive_file
        from app.core.config import settings
        from app.core.restore import atomic_restore

        config = await self._get_config(config_id)
        creds = json.loads(decrypt(config.credentials_encrypted))
        provider = self._cloud_provider_for(config, creds)

        engine_reinitialised = False
        try:
            files = await provider.list_files(CLOUD_BACKUP_PREFIX)
            if not files:
                raise ConflictError("No cloud backups found")
            latest_backup = sorted(files)[-1]

            restored_entries = 0
            restored_media = 0

            tmpdir = tempfile.mkdtemp()
            try:
                archive = Path(tmpdir) / "restore.tar.gz"
                await _download_backup_archive(provider, latest_backup, archive)
                extract_dir = Path(tmpdir) / "extracted"
                extract_dir.mkdir()
                # Extraction is synchronous and the archive can be large — offload it.
                await asyncio.to_thread(extract_archive_file, archive, extract_dir)

                extracted_db = extract_dir / "diarium.diarium"
                # Backward compat: accept old archives that used "dev.db"
                if not extracted_db.exists():
                    extracted_db = extract_dir / "dev.db"
                extracted_media = extract_dir / "media"

                if extracted_db.exists():
                    restored = await atomic_restore(
                        extracted_db=extracted_db,
                        extracted_media=extracted_media if extracted_media.exists() else None,
                        live_db=settings.db_path,
                        live_media=settings.MEDIA_DIR,
                        session=self.db,
                        extracted_wal=Path(f"{extracted_db}-wal"),
                        extracted_shm=Path(f"{extracted_db}-shm"),
                    )
                    engine_reinitialised = True
                    # The engine this request's session was bound to is gone —
                    # never touch it again. Count what came back on a fresh one.
                    counts = await _count_all_fresh()
                    if "database" in restored:
                        restored_entries = counts["entries"]
                    if "media" in restored:
                        restored_media = counts["media"]
                elif extracted_media.exists():
                    # No DB — just restore media if present
                    media_dir = settings.MEDIA_DIR
                    if media_dir.exists():
                        shutil.rmtree(str(media_dir))
                    shutil.copytree(str(extracted_media), str(media_dir))
                    restored_media = (await self.count_all())["media"]
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

            return {"entries_restored": restored_entries, "media_restored": restored_media}
        except Exception as e:
            if not engine_reinitialised:
                # The engine is still alive here — release partial work. After a
                # swap it is NOT (see _count_all_fresh); rolling back then would
                # raise PendingRollbackError and mask the real failure.
                await self.db.rollback()
            mapped = _classify_restore_error(e)
            if mapped is not e:
                raise mapped from e
            raise
        finally:
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
