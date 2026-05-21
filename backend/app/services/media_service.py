"""Business logic for media attachments."""
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, NotFoundError
from app.models.media import Media
from app.models.entry import Entry

logger = logging.getLogger(__name__)

# Magic-number signatures for dangerous file types (reject these)
_BLOCKED_SIGNATURES: dict[bytes, str] = {
    b"MZ": "Windows executable",
    b"\x7fELF": "Linux executable",
    b"<script": "HTML script tag",
    b"<?php": "PHP script",
    b"<!DOCTYPE": "HTML document",
}

# Allowed MIME type prefixes
_ALLOWED_MIME_PREFIXES = {"image/", "video/", "audio/", "application/pdf", "text/"}


class MediaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upload(
        self,
        entry_id: int,
        filename: str,
        content_type: str,
        file_data: bytes,
        caption: str | None = None,
    ) -> Media:
        """Store file on disk and create media record; reject > 25 MB."""
        if len(file_data) > settings.MAX_MEDIA_SIZE_BYTES:
            raise MediaSizeError(f"File exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")

        # Validate MIME type
        if not any(content_type.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
            raise MediaSizeError(f"File type '{content_type}' not allowed")

        # Check magic numbers for dangerous content
        for sig, label in _BLOCKED_SIGNATURES.items():
            if file_data[:len(sig)] == sig:
                logger.warning("Blocked upload of %s (detected %s)", filename, label)
                raise MediaSizeError(f"File type not allowed: detected {label}")

        # Sanitize filename — prevent path traversal
        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename:
            raise MediaSizeError("Invalid filename")

        # Verify entry exists
        entry = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        if not entry.scalar_one_or_none():
            raise NotFoundError(f"Entry {entry_id} not found")

        media_type = self._classify_media(content_type)
        ext = Path(safe_name).suffix or ".bin"
        stored_name = f"{uuid.uuid4()}{ext}"
        rel_path = f"{media_type}s/{stored_name}"
        full_path = settings.MEDIA_DIR / f"{media_type}s" / stored_name
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(file_data)

        media = Media(
            entry_id=entry_id,
            filename=safe_name,
            media_type=media_type,
            file_size=len(file_data),
            storage_path=rel_path,
            caption=caption,
        )
        self.db.add(media)
        await self.db.commit()
        await self.db.refresh(media)
        return media

    async def get(self, media_id: int) -> Media:
        """Return media metadata."""
        result = await self.db.execute(select(Media).where(Media.id == media_id))
        media = result.scalar_one_or_none()
        if not media:
            raise NotFoundError(f"Media {media_id} not found")
        return media

    async def get_file(self, media_id: int) -> tuple[bytes, str, str]:
        """Return (file_bytes, content_type, filename) from disk."""
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        return full_path.read_bytes(), self._media_content_type(media.media_type), media.filename

    async def delete(self, media_id: int) -> None:
        """Delete media record and remove file from disk."""
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if full_path.exists():
            full_path.unlink()
        await self.db.delete(media)
        await self.db.commit()

    async def delete_by_entry(self, entry_id: int) -> None:
        """Delete all media for an entry (cascade on soft-delete)."""
        result = await self.db.execute(select(Media).where(Media.entry_id == entry_id))
        for media in result.scalars().all():
            full_path = settings.MEDIA_DIR / media.storage_path
            if full_path.exists():
                full_path.unlink()
            await self.db.delete(media)
        await self.db.flush()

    async def list_for_entry(self, entry_id: int) -> list[Media]:
        """Return all media attachments for an entry."""
        result = await self.db.execute(
            select(Media).where(Media.entry_id == entry_id).order_by(Media.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    def _classify_media(content_type: str) -> str:
        """Map MIME type to media category."""
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"
        return "document"

    @staticmethod
    def _media_content_type(media_type: str) -> str:
        """Return a MIME type hint for the media category."""
        return {"image": "image/jpeg", "video": "video/mp4", "audio": "audio/mpeg"}.get(
            media_type, "application/octet-stream"
        )
