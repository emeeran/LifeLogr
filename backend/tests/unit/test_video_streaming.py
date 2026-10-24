"""Video serving — ranged streaming instead of a whole-file ``Response``.

``GET /videos/{id}/file`` used to read the entire clip into RAM and return it as
a single body, which breaks ``<video>`` seeking (no ``Range`` support).
"""

from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.entry_service import EntryService
from app.schemas.entry import EntryCreate
from app.services.video_service import VideoService

# Minimal MP4 header (ftyp box) — enough to pass the blocked-signature check.
_MP4_STUB = b"\x00\x00\x00\x18ftypmp42" + b"payload" * 40


async def _video(db_session: AsyncSession):
    entry = await EntryService(db_session).create(EntryCreate(entry_date=date(2026, 5, 1)))
    svc = VideoService(db_session)
    return await svc.upload(entry.id, "clip.mp4", "video/mp4", _MP4_STUB)


class TestVideoFileEndpoint:
    async def test_serves_inline_with_video_content_type(self, client: AsyncClient, db_session):
        note = await _video(db_session)
        r = await client.get(f"/api/v1/videos/{note.id}/file")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("video/")
        assert 'inline' in r.headers.get("content-disposition", "")
        assert r.headers.get("accept-ranges") == "bytes"
        assert r.content == _MP4_STUB

    async def test_range_request_returns_partial_content(self, client: AsyncClient, db_session):
        """The whole point: seeking needs Range support."""
        note = await _video(db_session)
        r = await client.get(
            f"/api/v1/videos/{note.id}/file", headers={"Range": "bytes=4-15"}
        )
        assert r.status_code == 206
        assert r.content == _MP4_STUB[4:16]
        assert r.headers["content-range"].startswith("bytes 4-15/")

    async def test_missing_file_on_disk_is_404(self, client: AsyncClient, db_session):
        note = await _video(db_session)
        VideoService(db_session).get_file_path(note).unlink(missing_ok=True)
        r = await client.get(f"/api/v1/videos/{note.id}/file")
        assert r.status_code == 404

    async def test_missing_video_is_404(self, client: AsyncClient):
        r = await client.get("/api/v1/videos/99999/file")
        assert r.status_code == 404
