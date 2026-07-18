"""Integration tests for analytics — overview, habits, words, heatmap."""

from httpx import AsyncClient

from app.models.media import Media


async def _seed(client: AsyncClient):
    await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "One two three"})
    await client.post(
        "/api/v1/entries", json={"entry_date": "2026-05-02", "body": "Four five six seven"}
    )
    await client.post(
        "/api/v1/entries", json={"entry_date": "2026-05-03", "body": "Eight nine", "mood": "happy"}
    )


class TestAnalytics:
    async def test_overview(self, client: AsyncClient):
        await _seed(client)
        r = await client.get("/api/v1/analytics/overview")
        assert r.status_code == 200
        data = r.json()
        assert data["total_entries"] >= 3

    async def test_overview_values(self, client: AsyncClient):
        """Lock the consolidated overview query: counts, word sum, date range, streaks."""
        await _seed(client)
        data = (await client.get("/api/v1/analytics/overview")).json()
        assert data["total_entries"] == 3
        # "One two three"(3) + "Four five six seven"(4) + "Eight nine"(2) = 9
        assert data["total_words"] == 9
        assert data["date_range_start"] == "2026-05-01"
        assert data["date_range_end"] == "2026-05-03"
        assert data["total_media"] == 0
        assert data["total_recordings"] == 0
        assert data["longest_streak"] >= 3  # three consecutive days

    async def test_media_stats_values(self, client: AsyncClient, db_session):
        """Lock the consolidated media-stats query (4 counts → 1) with real rows."""
        e = (
            await client.post("/api/v1/entries", json={"entry_date": "2026-05-10", "body": "x"})
        ).json()
        db_session.add_all(
            [
                Media(entry_id=e["id"], filename="a.png", media_type="image",
                      file_size=100, storage_path="a.png"),
                Media(entry_id=e["id"], filename="b.png", media_type="image",
                      file_size=200, storage_path="b.png"),
                Media(entry_id=e["id"], filename="c.mp4", media_type="video",
                      file_size=400, storage_path="c.mp4"),
            ]
        )
        await db_session.commit()
        data = (await client.get("/api/v1/analytics/media")).json()
        assert data["total_images"] == 2
        assert data["total_videos"] == 1
        assert data["total_recordings"] == 0
        assert data["total_size_bytes"] == 700

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
