"""Integration tests for reminders — CRUD."""
from httpx import AsyncClient


async def _create_reminder(client: AsyncClient):
    r = await client.post("/api/v1/reminders", json={
        "title": "Evening journal",
        "message": "Write!",
        "reminder_time": "21:00:00",
        "days_of_week": "0,1,2,3,4",
    })
    assert r.status_code == 201
    return r.json()


class TestReminderCRUD:
    async def test_create(self, client: AsyncClient):
        rem = await _create_reminder(client)
        assert rem["title"] == "Evening journal"

    async def test_list(self, client: AsyncClient):
        await _create_reminder(client)
        r = await client.get("/api/v1/reminders")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_get(self, client: AsyncClient):
        rem = await _create_reminder(client)
        r = await client.get(f"/api/v1/reminders/{rem['id']}")
        assert r.json()["title"] == "Evening journal"

    async def test_get_missing_404(self, client: AsyncClient):
        r = await client.get("/api/v1/reminders/9999")
        assert r.status_code == 404

    async def test_update(self, client: AsyncClient):
        rem = await _create_reminder(client)
        r = await client.patch(f"/api/v1/reminders/{rem['id']}", json={"title": "Morning"})
        assert r.json()["title"] == "Morning"

    async def test_delete(self, client: AsyncClient):
        rem = await _create_reminder(client)
        r = await client.delete(f"/api/v1/reminders/{rem['id']}")
        assert r.status_code == 204
