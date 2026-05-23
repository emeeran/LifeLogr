"""Business logic for media attachments."""
import io
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

# Image types that can be converted to WebP
_CONVERTIBLE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp", "image/tiff"}

# Max dimension for image resizing
_MAX_IMAGE_DIMENSION = 2048


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

        # Compress and convert images to WebP
        final_data = file_data
        final_ext = Path(safe_name).suffix or ".bin"
        if content_type in _CONVERTIBLE_IMAGE_TYPES:
            final_data, converted = self._compress_to_webp(file_data)
            if converted:
                final_ext = ".webp"

        stored_name = f"{uuid.uuid4()}{final_ext}"
        rel_path = f"{media_type}s/{stored_name}"
        full_path = settings.MEDIA_DIR / f"{media_type}s" / stored_name
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(final_data)

        media = Media(
            entry_id=entry_id,
            filename=safe_name,
            media_type=media_type,
            file_size=len(final_data),
            storage_path=rel_path,
            caption=caption,
        )
        self.db.add(media)
        await self.db.commit()
        await self.db.refresh(media)
        return media

    @staticmethod
    def _compress_to_webp(file_data: bytes) -> tuple[bytes, bool]:
        """Compress image and convert to WebP. Returns (data, was_converted)."""
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(file_data))

            # Strip EXIF orientation and convert to RGB if needed
            if hasattr(img, "transpose"):
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)

            # Resize if larger than max dimension
            if max(img.size) > _MAX_IMAGE_DIMENSION:
                img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION), Image.LANANCZOS)

            # Convert to RGB for WebP (handles RGBA, palette, etc.)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80, method=4)
            compressed = buf.getvalue()

            # Only use WebP if it's actually smaller
            if len(compressed) < len(file_data):
                logger.info(
                    "Image compressed to WebP: %d -> %d bytes (%.1f%% reduction)",
                    len(file_data), len(compressed),
                    (1 - len(compressed) / len(file_data)) * 100,
                )
                return compressed, True
            return file_data, False

        except Exception:
            logger.warning("Image compression failed, storing original", exc_info=True)
            return file_data, False

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
        content_type = self._media_content_type(media.media_type)
        # Serve WebP content type for converted images
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return full_path.read_bytes(), content_type, media.filename

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
