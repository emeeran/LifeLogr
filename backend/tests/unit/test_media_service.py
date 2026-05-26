"""Integration tests for media — upload, list, delete, classify."""

from httpx import AsyncClient


async def _entry(client: AsyncClient):
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "With media"}
    )
    return r.json()


class TestMediaClassify:
    async def test_classify_image(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "test"})
        assert r.status_code == 201
        # Media upload requires actual file — test classification helpers via service
        from app.services.media_service import MediaService

        assert MediaService._classify_media("image/png") == "image"
        assert MediaService._classify_media("video/mp4") == "video"
        assert MediaService._classify_media("audio/wav") == "audio"
        assert MediaService._classify_media("application/pdf") == "document"
