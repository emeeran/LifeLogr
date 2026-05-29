"""OCR service — extracts text from image media using Tesseract."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.media import Media
from app.models.ocr_result import OCRResult
from app.schemas.ocr import OCRResponse

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


class OCRService:
    """Runs Tesseract OCR on image media and caches results."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def extract_text(self, media_id: int, language: str = "eng") -> OCRResponse:
        """Extract text from an image. Returns cached result if available."""
        # Check cache first
        cached = await self._get_cached(media_id, language)
        if cached:
            return cached

        # Load media record
        media = await self._get_media(media_id)
        if not media.media_type.startswith("image/"):
            raise NotFoundError(f"Media {media_id} is not an image (type: {media.media_type})")

        # Read image file
        file_path = Path(settings.MEDIA_DIR) / media.storage_path
        if not file_path.exists():
            raise NotFoundError(f"Image file not found: {file_path}")

        # Run OCR (lazy imports — PIL/pytesseract are optional deps)
        try:
            from PIL import Image
            from pytesseract import image_to_string
        except ImportError as exc:
            raise ImportError(
                "OCR requires the 'ocr' extra. Install it with: uv pip install -e \".[ocr]\""
            ) from exc

        image = Image.open(file_path)
        extracted_text = await asyncio.to_thread(image_to_string, image, lang=language)
        extracted_text = extracted_text.strip()
        confidence = await asyncio.to_thread(self._compute_confidence, image, language)

        # Cache result
        result = OCRResult(
            media_id=media_id,
            extracted_text=extracted_text,
            confidence=confidence,
            language=language,
        )
        self.db.add(result)
        await self.db.commit()
        await self.db.refresh(result)

        return OCRResponse(
            media_id=media_id,
            extracted_text=result.extracted_text,
            confidence=result.confidence,
            language=result.language,
            processed_at=result.processed_at,
        )

    async def get_cached(self, media_id: int, language: str = "eng") -> OCRResponse:
        """Return cached OCR result or raise NotFoundError."""
        result = await self._get_cached(media_id, language)
        if not result:
            raise NotFoundError(f"No OCR result for media {media_id} (language: {language})")
        return result

    async def _get_cached(self, media_id: int, language: str) -> OCRResponse | None:
        """Check for cached OCR result."""
        row = await self.db.execute(
            select(OCRResult).where(OCRResult.media_id == media_id, OCRResult.language == language)
        )
        result = row.scalar_one_or_none()
        if not result:
            return None
        return OCRResponse(
            media_id=result.media_id,
            extracted_text=result.extracted_text,
            confidence=result.confidence,
            language=result.language,
            processed_at=result.processed_at,
        )

    async def _get_media(self, media_id: int) -> Media:
        """Fetch media record or raise NotFoundError."""
        row = await self.db.execute(select(Media).where(Media.id == media_id))
        media = row.scalar_one_or_none()
        if not media:
            raise NotFoundError(f"Media {media_id} not found")
        return media

    @staticmethod
    def _compute_confidence(image: "Image.Image", language: str) -> float:
        """Compute average OCR confidence from Tesseract output."""
        try:
            from pytesseract import image_to_data  # noqa: F811

            data = image_to_data(image, lang=language, output_type=2)
            confidences = [
                int(row.get("conf", -1)) for row in data if int(row.get("conf", -1)) >= 0
            ]
            return round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        except Exception:
            logger.warning("Failed to compute OCR confidence", exc_info=True)
            return 0.0
