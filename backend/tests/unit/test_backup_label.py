"""Tests for BackupConfig.label (named configs + Synology-as-webdav preset)."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.security import encrypt
from app.models.backup import BackupConfig, BackupSnapshot
from app.services.backup_service import BackupService


@pytest.mark.asyncio
async def test_config_label_roundtrips(client):
    payload = {
        "provider": "webdav",
        "label": "Synology NAS",
        "credentials": {
            "url": "https://nas.local:5006/lifelogr",
            "username": "u",
            "password": "p",
        },
    }
    r = await client.post("/api/v1/backup/config", json=payload)
    assert r.status_code == 201
    created = r.json()
    assert created["provider"] == "webdav"
    assert created["label"] == "Synology NAS"

    r2 = await client.get("/api/v1/backup/config")
    assert r2.status_code == 200
    assert any(c["label"] == "Synology NAS" for c in r2.json())

    await client.delete(f"/api/v1/backup/config/{created['id']}")


@pytest.mark.asyncio
async def test_config_label_optional(client):
    r = await client.post(
        "/api/v1/backup/config",
        json={
            "provider": "webdav",
            "credentials": {"url": "x", "username": "u", "password": "p"},
        },
    )
    assert r.status_code == 201
    assert r.json()["label"] is None
    await client.delete(f"/api/v1/backup/config/{r.json()['id']}")


@pytest.mark.asyncio
async def test_delete_backup_removes_snapshot_and_cloud_file(client, db_session, monkeypatch):
    """DELETE /backup/snapshots/{id} deletes the cloud file + the snapshot record."""
    config = BackupConfig(
        provider="google_drive",
        credentials_encrypted=encrypt(
            json.dumps({"client_id": "x", "client_secret": "y", "refresh_token": "z"})
        ),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    snap = BackupSnapshot(
        config_id=config.id,
        status="completed",
        backup_filename="lifelogr-backup-1.tar.gz",
    )
    db_session.add(snap)
    await db_session.commit()
    await db_session.refresh(snap)

    mock_provider = AsyncMock()
    mock_provider.delete = AsyncMock(return_value=None)
    mock_provider.close = AsyncMock(return_value=None)
    monkeypatch.setattr(BackupService, "_cloud_provider_for", lambda self, c, cr: mock_provider)

    r = await client.delete(f"/api/v1/backup/snapshots/{snap.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    assert body["remote_file_deleted"] is True
    mock_provider.delete.assert_awaited_once_with("lifelogr-backup-1.tar.gz")

    remaining = (
        await db_session.execute(select(BackupSnapshot).where(BackupSnapshot.id == snap.id))
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_delete_backup_without_filename_only_removes_record(client, db_session, monkeypatch):
    """An old snapshot with no stored filename just has its record removed."""
    config = BackupConfig(
        provider="webdav",
        credentials_encrypted=encrypt(json.dumps({"url": "u", "username": "n", "password": "p"})),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    snap = BackupSnapshot(config_id=config.id, status="completed")  # no backup_filename
    db_session.add(snap)
    await db_session.commit()
    await db_session.refresh(snap)

    # No provider should be built for a filename-less snapshot.
    built = AsyncMock()
    monkeypatch.setattr(BackupService, "_cloud_provider_for", lambda self, c, cr: built)

    r = await client.delete(f"/api/v1/backup/snapshots/{snap.id}")
    assert r.status_code == 200
    assert r.json()["remote_file_deleted"] is False
    built.assert_not_called()
