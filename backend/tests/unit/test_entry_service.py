"""Integration tests for entries — CRUD, soft-delete restore, 409 conflict, tags."""
from httpx import AsyncClient


async def _create_entry(client: AsyncClient, date="2026-05-08", body="Hello world", **kw):
    payload = {"entry_date": date, "body": body, **kw}
    r = await client.post("/api/v1/entries", json=payload)
    assert r.status_code == 201
    return r.json()


class TestEntryCreate:
    async def test_create_success(self, client: AsyncClient):
        entry = await _create_entry(client)
        assert entry["entry_date"] == "2026-05-08"
        assert entry["body"] == "Hello world"
        assert entry["is_deleted"] is False

    async def test_create_duplicate_date_succeeds(self, client: AsyncClient):
        """Multiple entries per date are allowed (unique constraint dropped)."""
        await _create_entry(client)
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-08", "body": "dup"})
        assert r.status_code == 201
        assert r.json()["body"] == "dup"

    async def test_create_with_tags(self, client: AsyncClient):
        tag = (await client.post("/api/v1/tags", json={"name": "travel"})).json()
        entry = await _create_entry(client, tag_ids=[tag["id"]])
        assert len(entry["tags"]) == 1
        assert entry["tags"][0]["name"] == "travel"

    async def test_create_empty_body_returns_422(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-08", "body": ""})
        assert r.status_code == 422


class TestEntryRead:
    async def test_get_entry(self, client: AsyncClient):
        entry = await _create_entry(client)
        r = await client.get(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 200
        assert r.json()["body"] == "Hello world"

    async def test_get_missing_returns_404(self, client: AsyncClient):
        r = await client.get("/api/v1/entries/9999")
        assert r.status_code == 404

    async def test_list_entries(self, client: AsyncClient):
        await _create_entry(client, date="2026-05-01")
        await _create_entry(client, date="2026-05-02", body="Second")
        r = await client.get("/api/v1/entries")
        data = r.json()
        assert data["total"] >= 2

    async def test_calendar_month(self, client: AsyncClient):
        await _create_entry(client, date="2026-06-15", body="June entry")
        r = await client.get("/api/v1/entries/calendar/2026/6")
        items = r.json()
        assert len(items) == 1
        assert items[0]["entry_date"] == "2026-06-15"


class TestEntryUpdate:
    async def test_update_body(self, client: AsyncClient):
        entry = await _create_entry(client)
        r = await client.patch(f"/api/v1/entries/{entry['id']}", json={"body": "Updated"})
        assert r.status_code == 200
        assert r.json()["body"] == "Updated"

    async def test_update_tags(self, client: AsyncClient):
        t1 = (await client.post("/api/v1/tags", json={"name": "a"})).json()
        t2 = (await client.post("/api/v1/tags", json={"name": "b"})).json()
        entry = await _create_entry(client, tag_ids=[t1["id"]])
        r = await client.patch(f"/api/v1/entries/{entry['id']}", json={"tag_ids": [t2["id"]]})
        tags = r.json()["tags"]
        assert len(tags) == 1
        assert tags[0]["name"] == "b"

    async def test_update_mood(self, client: AsyncClient):
        entry = await _create_entry(client)
        r = await client.patch(f"/api/v1/entries/{entry['id']}", json={"mood": "happy"})
        assert r.json()["mood"] == "happy"


class TestEntryDelete:
    async def test_soft_delete(self, client: AsyncClient):
        entry = await _create_entry(client)
        r = await client.delete(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 204
        r = await client.get(f"/api/v1/entries/{entry['id']}")
        assert r.status_code == 404

    async def test_create_after_delete_restores(self, client: AsyncClient):
        entry = await _create_entry(client, date="2026-05-08")
        await client.delete(f"/api/v1/entries/{entry['id']}")
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-08", "body": "Restored"})
        assert r.status_code == 201
        assert r.json()["body"] == "Restored"
