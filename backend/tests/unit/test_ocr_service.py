"""Integration tests for OCR — cached results via real DB, mocked Tesseract."""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.models.media import Media
from app.models.ocr_result import OCRResult
from app.services.ocr_service import OCRService
from app.core.exceptions import NotFoundError


async def _make_media(db: AsyncSession, media_type="image/png") -> Media:
    entry = Entry(entry_date=date(2026, 5, 1), body="test")
    db.add(entry)
    await db.flush()
    m = Media(
        entry_id=entry.id,
        filename="test.png",
        media_type=media_type,
        file_size=100,
        storage_path="test.png",
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


class TestOCRService:
    async def test_get_cached_raises_when_none(self, db_session: AsyncSession):
        m = await _make_media(db_session)
        svc = OCRService(db_session)
        with pytest.raises(NotFoundError):
            await svc.get_cached(m.id)

    async def test_get_cached_returns_existing(self, db_session: AsyncSession):
        m = await _make_media(db_session)
        ocr = OCRResult(media_id=m.id, extracted_text="hello", confidence=0.9, language="eng")
        db_session.add(ocr)
        await db_session.commit()
        svc = OCRService(db_session)
        result = await svc.get_cached(m.id)
        assert result.extracted_text == "hello"

    async def test_extract_text_non_image_raises(self, db_session: AsyncSession):
        m = await _make_media(db_session, media_type="video/mp4")
        svc = OCRService(db_session)
        with pytest.raises(NotFoundError):
            await svc.extract_text(m.id)
