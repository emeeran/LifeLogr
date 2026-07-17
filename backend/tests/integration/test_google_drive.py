"""Integration tests for Google Drive backup, sync, and OAuth features."""

import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
import respx
import httpx

from app.core.security import encrypt, decrypt
from app.models.backup import BackupConfig
from app.services.cloud_sync_service import GoogleDriveProvider
from app.services.backup_service import BackupService

# Use a test loopback port in tests
TEST_REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/google-drive/callback"


@pytest.mark.asyncio
async def test_ensure_valid_token_uses_existing():
    """Verify ensure_valid_token uses active access token if not expired."""
    creds = {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "access_token": "active-access-token",
        "refresh_token": "refresh-token",
        "token_expiry": str(time.time() + 3600),  # Valid for 1 hour
    }
    provider = GoogleDriveProvider(creds)
    token = await provider._ensure_valid_token()
    assert token == "active-access-token"


@pytest.mark.asyncio
@respx.mock
async def test_ensure_valid_token_refreshes():
    """Verify ensure_valid_token automatically refreshes access token if expired."""
    creds = {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "access_token": "old-access-token",
        "refresh_token": "refresh-token",
        "token_expiry": str(time.time() - 10),  # Expired
    }

    # Mock refresh endpoint
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "expires_in": 3600,
            },
        )
    )

    refresh_called = False

    async def mock_refresh(new_token, new_expiry):
        nonlocal refresh_called
        refresh_called = True
        assert new_token == "new-access-token"

    provider = GoogleDriveProvider(creds, on_token_refresh=mock_refresh)
    token = await provider._ensure_valid_token()

    assert token == "new-access-token"
    assert refresh_called is True


@pytest.mark.asyncio
@respx.mock
async def test_google_drive_provider_upload_create():
    """Test uploading a file that does not exist yet (creates new file)."""
    creds = {
        "access_token": "active-token",
        "token_expiry": str(time.time() + 1000),
    }
    provider = GoogleDriveProvider(creds)
    provider._folder_id = "folder-id"  # skip the find-or-create folder step

    # Mock file lookup (no files found)
    respx.get(url__startswith="https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    # Mock file upload
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart").mock(
        return_value=httpx.Response(200, json={"id": "new-file-id"})
    )

    result = await provider.upload("test-file.json", b"file-data")
    assert result == "test-file.json"


@pytest.mark.asyncio
@respx.mock
async def test_google_drive_provider_upload_update():
    """Test uploading a file that already exists (updates existing file)."""
    creds = {
        "access_token": "active-token",
        "token_expiry": str(time.time() + 1000),
    }
    provider = GoogleDriveProvider(creds)
    provider._folder_id = "folder-id"  # skip the find-or-create folder step

    # Mock file lookup (find existing file)
    respx.get(url__startswith="https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "existing-file-id", "name": "test-file.json"}]}
        )
    )

    # Mock file patch upload
    respx.patch(
        "https://www.googleapis.com/upload/drive/v3/files/existing-file-id?uploadType=media"
    ).mock(return_value=httpx.Response(200, json={"id": "existing-file-id"}))

    result = await provider.upload("test-file.json", b"new-file-data")
    assert result == "test-file.json"


@pytest.mark.asyncio
@respx.mock
async def test_google_drive_upload_falls_back_to_appdata_on_403():
    """A drive.appdata-only token (folder query 403) degrades to App Data.

    Reproduces the 're-link without revoke' state: the stored token can't see
    My Drive, so the visible-folder query 403s. The provider must still upload
    successfully — to the hidden App Data folder — and record last_location.
    """
    creds = {"access_token": "active-token", "token_expiry": str(time.time() + 1000)}
    provider = GoogleDriveProvider(creds)  # _folder_id NOT set → folder query runs

    # Visible-folder query → 403 (insufficientScopes)
    respx.get(url__regex=r"drive/v3/files\?q=.*mimeType.*").mock(
        return_value=httpx.Response(403, json={"error": {"message": "forbidden"}})
    )
    # App Data file lookup → not found
    respx.get(url__regex=r"drive/v3/files\?q=.*appDataFolder.*").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    # App Data upload → created
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart").mock(
        return_value=httpx.Response(200, json={"id": "appdata-file-id"})
    )

    result = await provider.upload("lifelogr-backup-test.tar.gz", b"data")
    assert result == "lifelogr-backup-test.tar.gz"
    assert provider.last_location == "appdata"
    assert provider._use_appdata is True


@pytest.mark.asyncio
@respx.mock
async def test_google_drive_provider_download():
    """Test downloading a file successfully."""
    creds = {
        "access_token": "active-token",
        "token_expiry": str(time.time() + 1000),
    }
    provider = GoogleDriveProvider(creds)
    provider._folder_id = "folder-id"  # skip the find-or-create folder step

    # Mock file lookup in the backup folder (list endpoint only — the media
    # download URL below is matched separately).
    respx.get(url__regex=r"https://www\.googleapis\.com/drive/v3/files\?").mock(
        return_value=httpx.Response(200, json={"files": [{"id": "file-id"}]})
    )

    # Mock download contents
    respx.get("https://www.googleapis.com/drive/v3/files/file-id?alt=media").mock(
        return_value=httpx.Response(200, content=b"downloaded-bytes")
    )

    content = await provider.download("test-file.json")
    assert content == b"downloaded-bytes"


@pytest.mark.asyncio
@respx.mock
async def test_google_drive_migrate_appdata_backups():
    """Hidden App Data backups are copied into the visible folder and removed."""
    creds = {"access_token": "active-token", "token_expiry": str(time.time() + 1000)}
    provider = GoogleDriveProvider(creds)
    provider._folder_id = "folder-id"

    # Any App Data query → the legacy backup; any folder query → empty.
    def _gdrive_get(request):
        if "spaces=appDataFolder" in str(request.url):
            return httpx.Response(
                200, json={"files": [{"id": "old-id", "name": "lifelogr-backup-1.tar.gz"}]}
            )
        return httpx.Response(200, json={"files": []})

    respx.get(url__regex=r"https://www\.googleapis\.com/drive/v3/files\?").mock(
        side_effect=_gdrive_get
    )
    respx.get("https://www.googleapis.com/drive/v3/files/old-id?alt=media").mock(
        return_value=httpx.Response(200, content=b"archive-bytes")
    )
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart").mock(
        return_value=httpx.Response(200, json={"id": "new-id"})
    )
    respx.delete("https://www.googleapis.com/drive/v3/files/old-id").mock(
        return_value=httpx.Response(204)
    )

    moved = await provider.migrate_appdata_backups()
    assert moved == 1


@pytest.mark.asyncio
async def test_oauth_auth_url_endpoint(client, db_session):
    """Test GET /api/v1/backup/google-drive/auth-url endpoint."""
    creds = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
    }
    db_session.add(
        BackupConfig(provider="google_drive", credentials_encrypted=encrypt(json.dumps(creds)))
    )
    await db_session.commit()

    response = await client.get("/api/v1/backup/google-drive/auth-url")
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "client_id=" in data["auth_url"]
    assert "redirect_uri=" in data["auth_url"]
    assert "state=" in data["auth_url"]


@pytest.mark.asyncio
@respx.mock
async def test_oauth_callback_endpoint(client, db_session):
    """Test GET /api/v1/backup/google-drive/callback success scenario."""
    db_session.add(
        BackupConfig(
            provider="google_drive",
            credentials_encrypted=encrypt(
                json.dumps({"client_id": "test-client-id", "client_secret": "test-client-secret"})
            ),
        )
    )
    await db_session.commit()

    # Mock Google Token exchange
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "returned-access-token",
                "refresh_token": "returned-refresh-token",
                "expires_in": 3600,
            },
        )
    )

    auth = await client.get("/api/v1/backup/google-drive/auth-url")
    state = parse_qs(urlparse(auth.json()["auth_url"]).query).get("state", [""])[0]

    response = await client.get(
        f"/api/v1/backup/google-drive/callback?code=mock-auth-code&state={state}"
    )
    assert response.status_code == 200
    assert "Google Drive Connected" in response.text

    # Verify BackupConfig is saved in database
    from sqlalchemy import select

    res = await db_session.execute(
        select(BackupConfig).where(BackupConfig.provider == "google_drive")
    )
    config = res.scalar_one()
    assert config is not None

    creds = json.loads(decrypt(config.credentials_encrypted))
    assert creds["access_token"] == "returned-access-token"
    assert creds["refresh_token"] == "returned-refresh-token"


@pytest.mark.asyncio
@respx.mock
async def test_oauth_callback_endpoint_missing_refresh_token(client, db_session):
    """Test GET /api/v1/backup/google-drive/callback when refresh token is missing."""
    db_session.add(
        BackupConfig(
            provider="google_drive",
            credentials_encrypted=encrypt(
                json.dumps({"client_id": "test-client-id", "client_secret": "test-client-secret"})
            ),
        )
    )
    await db_session.commit()

    # Mock Google Token exchange without a refresh token
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "returned-access-token",
                "expires_in": 3600,
            },
        )
    )

    auth = await client.get("/api/v1/backup/google-drive/auth-url")
    state = parse_qs(urlparse(auth.json()["auth_url"]).query).get("state", [""])[0]

    response = await client.get(
        f"/api/v1/backup/google-drive/callback?code=mock-auth-code&state={state}"
    )
    assert response.status_code == 400
    assert "No refresh token returned" in response.text


@pytest.mark.asyncio
@respx.mock
async def test_backup_service_run_backup_gdrive(db_session):
    """Test BackupService.run_backup executing with Google Drive provider."""
    # Seed database with BackupConfig
    creds = {
        "client_id": "test-id",
        "client_secret": "test-secret",
        "access_token": "valid-token",
        "refresh_token": "refresh-token",
        "token_expiry": str(time.time() + 1000),
    }
    config = BackupConfig(
        provider="google_drive",
        credentials_encrypted=encrypt(json.dumps(creds)),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    # Drive GETs: the folder lookup returns a folder (cached on the provider);
    # all other queries (App Data list during migration, file lookup) are empty.
    def _gdrive_get(request):
        if "mimeType" in str(request.url):
            return httpx.Response(200, json={"files": [{"id": "folder-id"}]})
        return httpx.Response(200, json={"files": []})

    respx.get(url__startswith="https://www.googleapis.com/drive/v3/files").mock(
        side_effect=_gdrive_get
    )
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart").mock(
        return_value=httpx.Response(200, json={"id": "backup-file-id"})
    )

    svc = BackupService(db_session)
    snapshot = await svc.run_backup(config.id)

    assert snapshot.status == "completed"
    assert snapshot.error_message is None
    assert snapshot.entries_synced == 0


@pytest.mark.asyncio
async def test_schedule_cloud_backup_registers_job(client, db_session):
    """Test POST /schedule with config_id registers a cloud backup job."""
    from app.services.scheduler_service import SchedulerService

    # Seed a Google Drive BackupConfig
    creds = {
        "client_id": "test-id",
        "client_secret": "test-secret",
        "access_token": "valid-token",
        "refresh_token": "refresh-token",
        "token_expiry": str(time.time() + 1000),
    }
    config = BackupConfig(
        provider="google_drive",
        credentials_encrypted=encrypt(json.dumps(creds)),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    # Schedule with config_id
    response = await client.post(f"/api/v1/backup/schedule?config_id={config.id}&cron=0+3+*+*+*")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "auto_backup"
    assert data["config_id"] == config.id
    assert data["cron"] == "0 3 * * *"

    # Verify the scheduler job is registered
    sched = SchedulerService.get_scheduler()
    job = sched.get_job("auto_backup")
    assert job is not None
    assert job.kwargs["config_id"] == config.id

    # Clean up scheduler singleton to avoid poisoning other test modules
    import app.services.scheduler_service as _sched_mod

    try:
        if _sched_mod._scheduler is not None:
            if _sched_mod._scheduler.running:
                _sched_mod._scheduler.shutdown(wait=False)
    except Exception:
        pass
    _sched_mod._scheduler = None


@pytest.mark.asyncio
async def test_schedule_cloud_backup_rejects_invalid_config_id(client, db_session):
    """Test POST /schedule with non-existent config_id returns 404."""
    response = await client.post("/api/v1/backup/schedule?config_id=9999&cron=0+3+*+*+*")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
