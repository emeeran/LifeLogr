"""Integration tests for backup — config, snapshots."""

from httpx import AsyncClient


class TestBackupConfig:
    async def test_create_config(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/backup/config",
            json={
                "provider": "webdav",
                "credentials": {"url": "https://dav.example.com", "username": "u", "password": "p"},
            },
        )
        assert r.status_code == 201

    async def test_list_configs(self, client: AsyncClient):
        await client.post(
            "/api/v1/backup/config",
            json={
                "provider": "webdav",
                "credentials": {"url": "https://dav.example.com"},
            },
        )
        r = await client.get("/api/v1/backup/config")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_test_connection_missing_config(self, client: AsyncClient):
        r = await client.post("/api/v1/backup/config/9999/test")
        assert r.status_code == 404


class TestBackupSnapshots:
    async def test_list_snapshots_empty(self, client: AsyncClient):
        r = await client.get("/api/v1/backup/snapshots")
        assert r.status_code == 200


class TestBoxBackup:
    """Box provider wiring — run_backup constructs BoxProvider and uploads."""

    async def test_run_backup_uses_box_provider(self, db_session):
        import json
        from unittest.mock import AsyncMock, patch

        from app.core.security import encrypt
        from app.models.backup import BackupConfig
        from app.services.backup_service import BackupService

        config = BackupConfig(
            provider="box",
            credentials_encrypted=encrypt(
                json.dumps(
                    {
                        "client_id": "id",
                        "client_secret": "secret",
                        "refresh_token": "rt",
                        "access_token": "at",
                        "token_expiry": "0",
                    }
                )
            ),
        )
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)

        box_instance = AsyncMock()
        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=box_instance) as mock_cls,
            patch.object(BackupService, "_create_backup_archive", AsyncMock(return_value=b"archive")),
            patch.object(BackupService, "count_all", AsyncMock(return_value={"entries": 0, "media": 0, "notes": 0})),
        ):
            svc = BackupService(db_session)
            snap = await svc.run_backup(config.id)

        mock_cls.assert_called_once()  # BoxProvider(creds, on_token_refresh=...)
        box_instance.upload.assert_awaited_once()
        await box_instance.close()
        assert snap.status == "completed"
