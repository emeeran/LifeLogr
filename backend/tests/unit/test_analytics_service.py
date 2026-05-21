"""Integration tests for analytics — overview, habits, words, heatmap."""
from httpx import AsyncClient


async def _seed(client: AsyncClient):
    await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "One two three"})
    await client.post("/api/v1/entries", json={"entry_date": "2026-05-02", "body": "Four five six seven"})
    await client.post("/api/v1/entries", json={"entry_date": "2026-05-03", "body": "Eight nine", "mood": "happy"})


class TestAnalytics:
    async def test_overview(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/overview")
        assert r.status_code == 200
        data = r.json()
        assert data["total_entries"] >= 3

    async def test_word_counts(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/words")
        assert r.status_code == 200

    async def test_moods(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/moods")
        assert r.status_code == 200

    async def test_heatmap(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/heatmap", params={"year": 2026})
        assert r.status_code == 200

    async def test_habits(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/habits")
        assert r.status_code == 200
