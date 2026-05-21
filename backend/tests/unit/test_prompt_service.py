"""Integration tests for prompts — today's prompt."""
from httpx import AsyncClient


class TestPrompts:
    async def test_get_today_not_found(self, client: AsyncClient):
        r = await client.get("/api/v1/prompts/today")
        assert r.status_code == 404
