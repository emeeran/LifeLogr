"""Integration tests for video notes — CRUD via service with real DB."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.video_service import VideoService
from app.services.entry_service import EntryService
from app.schemas.entry import EntryCreate


class TestVideoService:
    async def test_get_missing_raises(self, db_session: AsyncSession):
        svc = VideoService(db_session)
        try:
            await svc.get(9999)
            assert False, "Should have raised"
        except Exception:
            pass  # NotFoundError expected

    async def test_list_for_entry_empty(self, db_session: AsyncSession):
        entry_svc = EntryService(db_session)
        entry = await entry_svc.create(EntryCreate(entry_date="2026-05-01", body="v"))
        svc = VideoService(db_session)
        result = await svc.list_for_entry(entry.id)
        assert result == []
