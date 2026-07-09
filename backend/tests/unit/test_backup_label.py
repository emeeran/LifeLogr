"""Tests for BackupConfig.label (named configs + Synology-as-webdav preset)."""

import pytest


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
