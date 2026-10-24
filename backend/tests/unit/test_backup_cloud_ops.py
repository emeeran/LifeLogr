"""Cloud backup operations: retention, the in-progress claim, dispatch, and
how restore failures are reported.

Pins four fixes:
  * cloud archives are pruned to a retention count after each upload;
  * claiming the single in-progress slot is one atomic statement, so two
    processes can't both start a backup;
  * every cloud path builds its provider through the same dispatch (with a
    refresh callback that re-encrypts, upgrading legacy v1 tokens);
  * a restore failure is reported for what it is (network → 502, bad archive →
    400) instead of a blanket 409 "Restore failed", and post-restore counting
    never touches the session whose engine the restore just disposed.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt, token_version
from app.models.backup import BackupConfig
from app.services.backup_service import (
    BackupProviderError,
    BackupService,
    _classify_restore_error,
    cloud_backup_retention,
    select_stale_backups,
)


async def _make_config(db: AsyncSession, provider: str = "box") -> BackupConfig:
    config = BackupConfig(
        provider=provider,
        credentials_encrypted=encrypt(
            json.dumps(
                {
                    "client_id": "id",
                    "client_secret": "secret",
                    "refresh_token": "rt",
                    "access_token": "at",
                    "token_expiry": str(time.time() + 3600),
                }
            )
        ),
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


class _FakeProvider:
    """Minimal provider double: records deletes/uploads, serves a canned listing.

    Deliberately does *not* declare ``download_to_file`` on the class — tests
    that need it attach it to the instance, which keeps the streaming-vs-bytes
    preference observable.
    """

    instances: list["_FakeProvider"] = []

    def __init__(self, files: list[str]) -> None:
        self.files = list(files)
        self.deleted: list[str] = []
        self.uploaded: list[str] = []
        self.closed = False
        _FakeProvider.instances.append(self)

    async def list_files(self, prefix: str) -> list[str]:
        return [f for f in self.files if f.startswith(prefix)]

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        self.uploaded.append(path)
        return path

    async def delete(self, path: str) -> None:
        self.deleted.append(path)

    async def download(self, path: str) -> bytes:
        raise AssertionError("download() must not be used when streaming is available")

    async def close(self) -> None:
        self.closed = True


class _StreamingProvider(_FakeProvider):
    """Adds the class-level streaming download every real provider implements.

    Declared on the class (not the instance) because ``_download_backup_archive``
    looks the method up there: a method that exists only on an instance is
    indistinguishable from a test double's fabricated attribute, which would
    write nothing and leave the restore without an archive.
    """

    def __init__(self, files: list[str], payload: bytes = b"archive-bytes") -> None:
        super().__init__(files)
        self.payload = payload
        self.downloaded: list[str] = []

    async def download_to_file(self, path: str, local_path: str) -> str:
        from pathlib import Path

        self.downloaded.append(path)
        Path(local_path).write_bytes(self.payload)
        return path


def _archive_bytes() -> bytes:
    """A tiny valid .tar.gz with a ``diarium.diarium`` member.

    Restore's extraction runs for real (only the swap is stubbed), so the
    streamed payload has to be an archive tarfile can open.
    """
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="diarium.diarium")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"db--"))
    return buf.getvalue()


# ── Retention ────────────────────────────────────────────────────────────────


class TestCloudRetention:
    def test_keeps_newest_and_drops_oldest(self) -> None:
        files = [f"lifelogr-backup-2026-01-0{i}-000000.tar.gz" for i in range(1, 6)]
        assert select_stale_backups(files, keep_name=files[-1], retention=2) == files[:3]

    def test_counts_the_archive_just_uploaded(self) -> None:
        """The new archive counts even if the listing lags and omits it."""
        files = ["lifelogr-backup-1.tar.gz", "lifelogr-backup-2.tar.gz"]
        assert select_stale_backups(files, "lifelogr-backup-3.tar.gz", retention=2) == [
            "lifelogr-backup-1.tar.gz"
        ]

    def test_zero_or_negative_retention_keeps_everything(self) -> None:
        files = ["b", "a"]
        assert select_stale_backups(files, "c", retention=0) == []
        assert select_stale_backups(files, "c", retention=-3) == []

    async def test_run_backup_prunes_oldest_beyond_retention(
        self, db_session: AsyncSession, tmp_path
    ) -> None:
        """After a successful upload the provider is pruned to the count."""
        config = await _make_config(db_session)
        files = [f"lifelogr-backup-2026010{d}-000000.tar.gz" for d in range(1, 6)]
        fake = _FakeProvider(files)
        archive = tmp_path / "archive.tar.gz"
        archive.write_bytes(b"archive")

        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake),
            patch.object(
                BackupService, "_build_backup_archive", AsyncMock(return_value=archive)
            ),
            patch.object(
                BackupService, "count_all", AsyncMock(return_value={"entries": 0, "media": 0})
            ),
            patch("app.services.backup_service.cloud_backup_retention", lambda: 2),
        ):
            snapshot = await BackupService(db_session).run_backup(config.id)

        assert snapshot.status == "completed"
        assert fake.uploaded == [snapshot.backup_filename]
        # Oldest four gone; the newest seeded archive and the fresh upload stay.
        assert fake.deleted == files[:4]
        assert files[-1] not in fake.deleted
        assert snapshot.backup_filename not in fake.deleted
        assert fake.closed is True

    async def test_prune_failure_does_not_fail_the_backup(
        self, db_session: AsyncSession, tmp_path
    ) -> None:
        config = await _make_config(db_session)
        fake = _FakeProvider(["lifelogr-backup-1.tar.gz"])
        fake.delete = AsyncMock(side_effect=httpx.ConnectError("provider hiccup"))
        archive = tmp_path / "archive.tar.gz"
        archive.write_bytes(b"archive")

        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake),
            patch.object(
                BackupService, "_build_backup_archive", AsyncMock(return_value=archive)
            ),
            patch.object(
                BackupService, "count_all", AsyncMock(return_value={"entries": 0, "media": 0})
            ),
        ):
            snapshot = await BackupService(db_session).run_backup(config.id)

        assert snapshot.status == "completed"

    def test_env_override_is_validated(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.services.backup_service.DEFAULT_CLOUD_BACKUP_RETENTION", 14, raising=False
        )
        monkeypatch.setenv("BACKUP_CLOUD_RETENTION", "7")
        assert cloud_backup_retention() == 7
        for bad in ("0", "-2", "many", ""):
            monkeypatch.setenv("BACKUP_CLOUD_RETENTION", bad)
            assert cloud_backup_retention() == 14


# ── In-progress claim ────────────────────────────────────────────────────────


class TestInProgressClaim:
    async def test_second_run_is_rejected(self, db_session: AsyncSession) -> None:
        """A snapshot already in progress blocks a new one (409)."""
        from app.core.exceptions import ConflictError
        from app.models.backup import BackupSnapshot

        config = await _make_config(db_session)
        db_session.add(BackupSnapshot(config_id=config.id, status="in_progress"))
        await db_session.commit()

        with pytest.raises(ConflictError, match="already in progress"):
            await BackupService(db_session)._begin_snapshot(config.id)

    async def test_claim_is_atomic_and_returns_the_row(self, db_session: AsyncSession) -> None:
        config = await _make_config(db_session)
        snapshot = await BackupService(db_session)._begin_snapshot(config.id)
        assert snapshot.status == "in_progress"
        assert snapshot.config_id == config.id

    async def test_stale_in_progress_is_reclaimed(self, db_session: AsyncSession) -> None:
        """A snapshot abandoned by a crashed run doesn't block backups forever."""
        from datetime import datetime, timedelta, timezone

        from app.models.backup import BackupSnapshot

        config = await _make_config(db_session)
        db_session.add(
            BackupSnapshot(
                config_id=config.id,
                status="in_progress",
                started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
        )
        await db_session.commit()

        snapshot = await BackupService(db_session)._begin_snapshot(config.id)
        assert snapshot.status == "in_progress"
        reclaimed = (
            await db_session.execute(
                text_select_interrupted(config.id)
            )
        ).scalar_one_or_none()
        assert reclaimed == "Interrupted: previous run did not complete"


def text_select_interrupted(config_id: int):
    from sqlalchemy import select

    from app.models.backup import BackupSnapshot

    return (
        select(BackupSnapshot.error_message)
        .where(
            BackupSnapshot.config_id == config_id,
            BackupSnapshot.status == "failed",
        )
        .order_by(BackupSnapshot.id)
    )


# ── Provider dispatch ────────────────────────────────────────────────────────


class TestProviderDispatch:
    async def test_unknown_provider_is_a_validation_error(self, db_session) -> None:
        from app.core.exceptions import ValidationError

        config = BackupConfig(provider="floppydisk", credentials_encrypted="x")
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)

        with pytest.raises(ValidationError, match="Unsupported backup provider"):
            BackupService(db_session)._cloud_provider_for(config, {})

    async def test_refresh_callback_reencrypts_and_upgrades_v1(
        self, db_session: AsyncSession
    ) -> None:
        """A token refresh upgrades a legacy v1 credential, not just re-writes it."""
        import base64

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        import app.routers.sync as sync_router
        from app.core import security
        from app.core.security import decrypt

        legacy_creds = json.dumps(
            {"refresh_token": "rt", "access_token": "old", "token_expiry": "0"}
        )
        nonce = b"\x00" * 12
        ct = AESGCM(security._v1_key).encrypt(nonce, legacy_creds.encode(), None)
        config = BackupConfig(
            provider="dropbox",
            credentials_encrypted=base64.b64encode(nonce + ct).decode(),
        )
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)
        assert token_version(config.credentials_encrypted) == 1  # legacy token in place

        provider = await sync_router._get_provider(db_session, "dropbox")
        await provider._on_token_refresh("new-token", "9999")

        assert token_version(config.credentials_encrypted) == 2
        assert json.loads(decrypt(config.credentials_encrypted))["access_token"] == "new-token"

    async def test_sync_and_backup_share_one_construction(
        self, db_session: AsyncSession
    ) -> None:
        """sync's provider comes from BackupService._cloud_provider_for."""
        import app.routers.sync as sync_router
        from app.services.cloud_sync_service import NextcloudProvider

        await _make_config(db_session, provider="webdav")
        shared = NextcloudProvider(
            base_url="https://dav.example.com", username="u", password="p"
        )
        with patch.object(
            BackupService, "_cloud_provider_for", return_value=shared
        ) as spy:
            provider = await sync_router._get_provider(db_session, "webdav")
            assert provider is shared
            spy.assert_called_once()

    async def test_unknown_provider_over_sync_endpoint_is_400(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A config row with an unknown provider is a client error, not a 500.

        The old sync dispatch raised a bare ``ValueError``, which escaped as a
        500 with a stack trace for what is a bad request.
        """
        db_session.add(
            BackupConfig(
                provider="floppydisk",
                credentials_encrypted=encrypt(json.dumps({"refresh_token": "rt"})),
            )
        )
        await db_session.commit()

        r = await client.post(
            "/api/v1/sync/cloud/push", json={"provider": "floppydisk", "passphrase": None}
        )

        assert r.status_code == 400

    async def test_delete_backup_uses_the_shared_dispatch(self, db_session) -> None:
        from app.models.backup import BackupSnapshot

        config = await _make_config(db_session)
        db_session.add(
            BackupSnapshot(
                config_id=config.id, status="completed", backup_filename="lifelogr-backup-1.tar.gz"
            )
        )
        await db_session.commit()
        snap = (await db_session.execute(text_select_snapshot())).scalar_one()

        fake = _FakeProvider(["lifelogr-backup-1.tar.gz"])
        _FakeProvider.instances.clear()
        with patch("app.services.cloud_sync_service.BoxProvider", return_value=fake):
            result = await BackupService(db_session).delete_backup(snap.id)

        assert result["remote_file_deleted"] is True
        assert fake.deleted == ["lifelogr-backup-1.tar.gz"]
        assert fake.closed is True


def text_select_snapshot():
    from sqlalchemy import select

    from app.models.backup import BackupSnapshot

    return select(BackupSnapshot)


# ── Restore error mapping + session hygiene ─────────────────────────────────


class TestRestoreErrorMapping:
    def test_provider_fault_becomes_502_class(self) -> None:
        mapped = _classify_restore_error(httpx.ConnectError("no route to host"))
        assert isinstance(mapped, BackupProviderError)

    def test_bad_archive_becomes_400_class(self) -> None:
        from app.core.exceptions import ValidationError

        assert isinstance(_classify_restore_error(ValueError("not a zip")), ValidationError)

    def test_classified_and_unknown_errors_pass_through(self) -> None:
        conflict = __import__("app.core.exceptions", fromlist=["ConflictError"]).ConflictError("x")
        assert _classify_restore_error(conflict) is conflict
        boom = RuntimeError("disk on fire")
        assert _classify_restore_error(boom) is boom

    async def test_network_failure_returns_502(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        config = await _make_config(db_session, provider="webdav")
        failing = _FakeProvider([])
        failing.list_files = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))

        with patch("app.services.cloud_sync_service.NextcloudProvider", return_value=failing):
            r = await client.post("/api/v1/backup/restore", json={"config_id": config.id})

        assert r.status_code == 502
        assert "timed out" in r.json()["detail"]

    async def test_no_backups_is_still_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        config = await _make_config(db_session, provider="webdav")
        empty = _FakeProvider([])

        with patch("app.services.cloud_sync_service.NextcloudProvider", return_value=empty):
            r = await client.post("/api/v1/backup/restore", json={"config_id": config.id})

        assert r.status_code == 409

    async def test_corrupt_archive_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        config = await _make_config(db_session, provider="webdav")
        fake = _StreamingProvider(["lifelogr-backup-1.tar.gz"], payload=b"not a tar.gz")

        with patch("app.services.cloud_sync_service.NextcloudProvider", return_value=fake):
            r = await client.post("/api/v1/backup/restore", json={"config_id": config.id})

        assert r.status_code == 400

    async def test_streams_the_download_instead_of_buffering(
        self, db_session: AsyncSession
    ) -> None:
        """The provider's file download is used; the bytes fallback is not."""
        config = await _make_config(db_session, provider="webdav")
        fake = _StreamingProvider(["lifelogr-backup-1.tar.gz"], payload=_archive_bytes())

        with (
            patch("app.services.cloud_sync_service.NextcloudProvider", return_value=fake),
            patch(
                "app.core.restore.atomic_restore", new=AsyncMock(return_value=["database"])
            ),
            patch(
                "app.services.backup_service._count_all_fresh",
                AsyncMock(return_value={"entries": 0, "media": 0, "notes": 0}),
            ),
        ):
            await BackupService(db_session).restore(config.id)

        assert fake.downloaded == ["lifelogr-backup-1.tar.gz"]
        # download() is the bytes path — it raises AssertionError if ever used.


class TestRestoreSessionHygiene:
    async def test_counts_are_read_on_a_fresh_session(self, db_session) -> None:
        """Post-restore counts must not use the session whose engine was disposed.

        atomic_restore tears the engine down and rebuilds it, so the request's
        session is dead afterwards — running the count on it raised
        PendingRollbackError and reported a successful restore as failed.
        """
        config = await _make_config(db_session)
        fake = _StreamingProvider(["lifelogr-backup-1.tar.gz"], payload=_archive_bytes())

        used_sessions: list[AsyncSession] = []
        fresh_session = AsyncMock(name="fresh-session")

        class _FreshSessionFactory:
            """Stands in for async_session(): yields the fresh session."""

            def __init__(self, session: AsyncMock) -> None:
                self._session = session
                self.entered = False

            def __call__(self) -> "_FreshSessionFactory":
                return self

            async def __aenter__(self) -> AsyncMock:
                self.entered = True
                return self._session

            async def __aexit__(self, *exc: object) -> bool:
                return False

        async def spy_count_all(self) -> dict[str, int]:
            used_sessions.append(self.db)
            return {"entries": 4, "media": 1, "notes": 0}

        with (
            patch("app.services.cloud_sync_service.BoxProvider", return_value=fake),
            patch.object(BackupService, "count_all", new=spy_count_all),
            patch(
                "app.core.database.async_session", _FreshSessionFactory(fresh_session)
            ),
            patch(
                "app.core.restore.atomic_restore",
                new=AsyncMock(return_value=["database", "media"]),
            ) as mock_restore,
        ):
            result = await BackupService(db_session).restore(config.id)

        assert result == {"entries_restored": 4, "media_restored": 1}
        mock_restore.assert_awaited_once()
        # The count ran on the fresh session, never on the request's session.
        assert used_sessions == [fresh_session]
        assert fresh_session.rollback.await_count == 0


class TestRunEndpoint:
    async def test_run_is_synchronous_200(self, client: AsyncClient, db_session) -> None:
        """POST /backup/run runs the backup and returns 200 with the snapshot.

        It used to declare 202 "accepted in the background" while blocking on
        the whole upload.
        """
        from datetime import datetime, timezone

        from app.models.backup import BackupSnapshot

        config = await _make_config(db_session)
        now = datetime.now(timezone.utc)
        snapshot = BackupSnapshot(
            id=1,
            config_id=config.id,
            status="completed",
            entries_synced=0,
            media_synced=0,
            started_at=now,
            completed_at=now,
            backup_filename="lifelogr-backup-1.tar.gz",
        )

        with patch.object(BackupService, "run_backup", AsyncMock(return_value=snapshot)):
            r = await client.post("/api/v1/backup/run", json={"config_id": config.id})

        assert r.status_code == 200
        assert r.json()["status"] == "completed"
