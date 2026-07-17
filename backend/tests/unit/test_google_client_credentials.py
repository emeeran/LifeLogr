"""Tests for in-app Google OAuth client credentials (Calendar/Tasks/Contacts sync).

Mirrors the Drive pattern: client_id/secret stored encrypted in
``BackupConfig(provider="google_sync")``, DB-first with env fallback. The
auth-url + callback + token exchange all resolve creds this way so the
installed app no longer depends on a ``.env`` at its CWD.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.security import decrypt, encrypt
from app.models.backup import BackupConfig
from app.routers.google_sync import _resolve_client_creds


@pytest.fixture(autouse=True)
def _blank_env_google_creds(monkeypatch):
    """Tests must not inherit real creds from the dev ``backend/.env``."""
    from app.routers import google_sync as router

    monkeypatch.setattr(router.settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(router.settings, "GOOGLE_CLIENT_SECRET", "")


async def _stored_config(db) -> BackupConfig | None:
    return (
        await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_sync"))
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_resolve_creds_prefers_db_over_env(db_session):
    db_session.add(
        BackupConfig(
            provider="google_sync",
            credentials_encrypted=encrypt(json.dumps({"client_id": "db-id", "client_secret": "db-secret"})),
        )
    )
    await db_session.commit()
    client_id, client_secret = await _resolve_client_creds(db_session)
    assert client_id == "db-id"
    assert client_secret == "db-secret"


@pytest.mark.asyncio
async def test_resolve_creds_falls_back_to_env(db_session, monkeypatch):
    from app.routers import google_sync as router

    monkeypatch.setattr(router.settings, "GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setattr(router.settings, "GOOGLE_CLIENT_SECRET", "env-secret")
    client_id, client_secret = await _resolve_client_creds(db_session)
    assert client_id == "env-id"
    assert client_secret == "env-secret"


@pytest.mark.asyncio
async def test_resolve_creds_empty_when_neither(db_session):
    client_id, client_secret = await _resolve_client_creds(db_session)
    assert client_id == ""
    assert client_secret == ""


@pytest.mark.asyncio
async def test_put_then_get_client_credentials(client):
    resp = await client.put(
        "/api/v1/google/client-credentials",
        json={"client_id": "abc.apps.googleusercontent.com", "client_secret": "shh"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["client_id"] == "abc.apps.googleusercontent.com"

    resp = await client.get("/api/v1/google/client-credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["client_id"] == "abc.apps.googleusercontent.com"
    assert "client_secret" not in body  # secret never returned


@pytest.mark.asyncio
async def test_get_client_credentials_not_configured(client):
    resp = await client.get("/api/v1/google/client-credentials")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_put_credentials_stores_only_id_and_secret_encrypted(client, db_session):
    resp = await client.put(
        "/api/v1/google/client-credentials",
        json={"client_id": "id1", "client_secret": "sec1"},
    )
    assert resp.status_code == 200
    cfg = await _stored_config(db_session)
    assert cfg is not None
    stored = json.loads(decrypt(cfg.credentials_encrypted))
    assert stored == {"client_id": "id1", "client_secret": "sec1"}


@pytest.mark.asyncio
async def test_put_rejects_blank(client):
    resp = await client.put(
        "/api/v1/google/client-credentials",
        json={"client_id": "", "client_secret": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auth_url_400_when_no_credentials(client):
    resp = await client.get("/api/v1/google/auth-url")
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_auth_url_ok_when_db_credentials_set(client):
    await client.put(
        "/api/v1/google/client-credentials",
        json={"client_id": "xyz.apps.googleusercontent.com", "client_secret": "s"},
    )
    resp = await client.get("/api/v1/google/auth-url")
    assert resp.status_code == 200
    url = resp.json()["auth_url"]
    assert "accounts.google.com" in url
    assert "xyz.apps.googleusercontent.com" in url


@pytest.mark.asyncio
async def test_exchange_code_requires_creds():
    from app.services.google_oauth import exchange_code

    with pytest.raises(RuntimeError):
        await exchange_code("some-code", "", "")
