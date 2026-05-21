"""Integration tests for search — uses LIKE-based search via entries API."""
from httpx import AsyncClient


class TestSearch:
    async def test_search_returns_results(self, client: AsyncClient):
        await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "Python programming"})
        # Use the entries search endpoint (which uses ilike fallback when FTS isn't populated)
        r = await client.get("/api/v1/entries/search", params={"q": "Python"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    async def test_search_empty_results(self, client: AsyncClient):
        await client.post("/api/v1/entries", json={"entry_date": "2026-05-02", "body": "Hello world"})
        r = await client.get("/api/v1/entries/search", params={"q": "xyznonexistent"})
        assert r.status_code == 200
        assert r.json()["total"] == 0
