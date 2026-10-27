"""Cached WebP thumbnails for the media timeline.

The timeline grid loads ~50 images per page; serving full originals there
decoded gigabytes in WebKit and OOM-killed the machine (2026-10-27). ``/thumb``
must return a small WebP, cache it under ``thumbs/``, reuse the cache, and 404
for non-images (only videos/audio keep using ``/file``).
"""

from pathlib import Path

from httpx import AsyncClient
from PIL import Image

from app.core.config import settings


def _png_bytes(size: int = 64) -> bytes:
    """A real PNG — the hand-made 1×1 stub trips exif_transpose in Pillow."""
    import io

    buf = io.BytesIO()
    Image.new("RGB", (size, size), (30, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def _upload(client: AsyncClient, payload: bytes, filename: str, content_type: str) -> dict:
    r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "x"})
    assert r.status_code == 201
    entry_id = r.json()["id"]
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry_id)},
        files={"file": (filename, payload, content_type)},
    )
    assert r.status_code == 201
    return r.json()


class TestThumbnails:
    async def test_thumb_served_and_cached(self, client: AsyncClient):
        # MEDIA_DIR persists across tests in this process — compare, don't count.
        before = set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp"))
        media = await _upload(client, _png_bytes(), "pic.png", "image/png")
        r = await client.get(f"/api/v1/media/{media['id']}/thumb")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/webp")
        assert len(set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp")) - before) == 1
        # Second request serves the cached file, not a fresh render.
        assert (await client.get(f"/api/v1/media/{media['id']}/thumb")).status_code == 200
        assert len(set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp")) - before) == 1

    async def test_corrupt_image_falls_back_to_original(self, client: AsyncClient):
        """A bad file must degrade to the original, never 500 the grid."""
        # MEDIA_DIR persists across tests in this process — compare, don't count.
        before = set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp"))
        media = await _upload(client, b"\x89PNG\r\n\x1a\nnot-really", "broken.png", "image/png")
        r = await client.get(f"/api/v1/media/{media['id']}/thumb")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp")) == before

    async def test_non_image_404s(self, client: AsyncClient):
        media = await _upload(client, b"hello", "note.txt", "text/plain")
        r = await client.get(f"/api/v1/media/{media['id']}/thumb")
        assert r.status_code == 404

    async def test_delete_removes_cached_thumb(self, client: AsyncClient):
        # MEDIA_DIR persists across tests in this process — compare, don't count.
        before = set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp"))
        media = await _upload(client, _png_bytes(), "pic.png", "image/png")
        await client.get(f"/api/v1/media/{media['id']}/thumb")
        await client.delete(f"/api/v1/media/{media['id']}")
        assert set(Path(settings.MEDIA_DIR, "thumbs").glob("*.webp")) == before
