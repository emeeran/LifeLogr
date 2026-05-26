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
