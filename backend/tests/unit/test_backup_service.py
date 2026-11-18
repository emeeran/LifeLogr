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

    async def test_run_backup_uses_box_provider(self, db_session, tmp_path):
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

        # _build_backup_archive now returns an on-disk Path (streamed upload),
        # so hand it a real temp file the finally can unlink.
        archive = tmp_path / "fake-archive.tar.gz"
        archive.write_bytes(b"archive")
        box_instance = AsyncMock()
        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=box_instance) as mock_cls,
            patch.object(BackupService, "_build_backup_archive", AsyncMock(return_value=archive)),
            patch.object(BackupService, "count_all", AsyncMock(return_value={"entries": 0, "media": 0, "notes": 0})),
        ):
            svc = BackupService(db_session)
            snap = await svc.run_backup(config.id)

        mock_cls.assert_called_once()  # BoxProvider(creds, on_token_refresh=...)
        box_instance.upload_file.assert_awaited_once()
        await box_instance.close()
        assert snap.status == "completed"
        # The streamed temp archive is cleaned up after upload.
        assert not archive.exists()


class TestCloudRestore:
    """BackupService.restore() — cloud download → extract → atomic_restore.

    The local import path is covered elsewhere; this locks the cloud-restore
    orchestration (provider.download, traversal-guarded extraction, hand-off to
    atomic_restore + client close) that was previously untested.
    """

    async def test_restore_downloads_extracts_and_hands_off(self, db_session):
        import io
        import json
        import tarfile
        from unittest.mock import AsyncMock, patch

        from app.core.config import settings
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

        # Craft a tar.gz containing a diarium.diarium (what restore() looks for).
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"fake-db-bytes"
            info = tarfile.TarInfo(name="diarium.diarium")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive_bytes = buf.getvalue()

        fake_provider = AsyncMock()
        fake_provider.list_files = AsyncMock(return_value=["lifelogr-backup-1.tar.gz"])
        fake_provider.download = AsyncMock(return_value=archive_bytes)
        fake_provider.close = AsyncMock()

        # atomic_restore swaps the live DB (tested separately) — stub it so this
        # test exercises only the restore() orchestration. Extraction runs for real.
        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake_provider),
            patch(
                "app.core.restore.atomic_restore",
                new=AsyncMock(return_value=["database"]),
            ) as mock_atomic,
        ):
            svc = BackupService(db_session)
            result = await svc.restore(config.id)

        # The latest backup was downloaded.
        fake_provider.download.assert_awaited_once_with("lifelogr-backup-1.tar.gz")
        # The extracted diarium.diarium was handed to atomic_restore with the live db.
        mock_atomic.assert_awaited_once()
        kwargs = mock_atomic.call_args.kwargs
        assert kwargs["extracted_db"].name == "diarium.diarium"
        assert kwargs["live_db"] == settings.db_path
        # The cloud client was closed.
        fake_provider.close.assert_awaited_once()
        assert result == {"entries_restored": 0, "media_restored": 0}
