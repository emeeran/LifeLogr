"""Integration tests for Google Drive backup, sync, and OAuth features."""

import json
import time
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
async def test_google_drive_provider_download():
    """Test downloading a file successfully."""
    creds = {
        "access_token": "active-token",
        "token_expiry": str(time.time() + 1000),
    }
    provider = GoogleDriveProvider(creds)

    # Mock file lookup (matches only the search endpoint with query params)
    respx.get(
        url__regex=r"https://www\.googleapis\.com/drive/v3/files\?.*spaces=appDataFolder"
    ).mock(return_value=httpx.Response(200, json={"files": [{"id": "file-id"}]}))

    # Mock download contents
    respx.get("https://www.googleapis.com/drive/v3/files/file-id?alt=media").mock(
        return_value=httpx.Response(200, content=b"downloaded-bytes")
    )

    content = await provider.download("test-file.json")
    assert content == b"downloaded-bytes"


@pytest.mark.asyncio
async def test_oauth_auth_url_endpoint(client, db_session):
    """Test GET /api/v1/backup/google-drive/auth-url endpoint."""
    response = await client.get("/api/v1/backup/google-drive/auth-url")
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "client_id=" in data["auth_url"]
    assert "redirect_uri=" in data["auth_url"]


@pytest.mark.asyncio
@respx.mock
async def test_oauth_callback_endpoint(client, db_session):
    """Test GET /api/v1/backup/google-drive/callback success scenario."""
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

    response = await client.get("/api/v1/backup/google-drive/callback?code=mock-auth-code")
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

    response = await client.get("/api/v1/backup/google-drive/callback?code=mock-auth-code")
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

    # Mock Google Drive provider operations
    respx.get(url__startswith="https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart").mock(
        return_value=httpx.Response(200, json={"id": "backup-file-id"})
    )

    svc = BackupService(db_session)
    snapshot = await svc.run_backup(config.id)

    assert snapshot.status == "completed"
    assert snapshot.error_message is None
    assert snapshot.entries_synced == 0
