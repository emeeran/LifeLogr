"""Integration tests for sync — enqueue, pending, flush."""

from httpx import AsyncClient


class TestSyncQueue:
    async def test_enqueue(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/sync/enqueue",
            json={
                "operation": "create",
                "entity_type": "entry",
                "entity_id": 1,
                "payload": {"body": "test"},
            },
        )
        assert r.status_code == 201
        assert r.json()["operation"] == "create"

    async def test_get_pending(self, client: AsyncClient):
        await client.post(
            "/api/v1/sync/enqueue",
            json={
                "operation": "update",
                "entity_type": "entry",
                "entity_id": 2,
                "payload": {},
            },
        )
        r = await client.get("/api/v1/sync/pending")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_sync_status(self, client: AsyncClient):
        r = await client.get("/api/v1/sync/status")
        assert r.status_code == 200
        assert "pending_count" in r.json()

    async def test_flush(self, client: AsyncClient):
        await client.post(
            "/api/v1/sync/enqueue",
            json={
                "operation": "delete",
                "entity_type": "entry",
                "entity_id": 3,
                "payload": {},
            },
        )
        r = await client.post("/api/v1/sync/flush")
        assert r.status_code == 200
        assert r.json()["synced"] >= 1
