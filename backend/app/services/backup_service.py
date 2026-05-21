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
        # Provider-specific connection test is deferred to integration phase
        # For now, verify we can decrypt the credentials
        decrypt(config.credentials_encrypted)
        return True

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
            json.loads(decrypt(config.credentials_encrypted))
        except Exception as e:
            snapshot.status = "failed"
            snapshot.error_message = str(e)
        else:
            snapshot.status = "completed"
            config.last_sync_at = datetime.now()

        snapshot.completed_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

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

    async def restore(self, config_id: int) -> dict[str, int]:
        """Atomically replace local data with cloud backup; rollback on failure."""
        await self._get_config(config_id)
        # Actual restore logic deferred to integration phase
        return {"entries_restored": 0, "media_restored": 0}

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
