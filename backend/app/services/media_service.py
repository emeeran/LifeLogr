"""Business logic for media attachments."""

import io
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
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
_CONVERTIBLE_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

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
            if file_data[: len(sig)] == sig:
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
        except ImportError:
            logger.warning(
                "Image compression requires the 'image' extra. "
                'Install it with: uv pip install -e ".[image]". Storing original.'
            )
            return file_data, False

        try:
            img: Any = Image.open(io.BytesIO(file_data))

            # Strip EXIF orientation and convert to RGB if needed
            if hasattr(img, "transpose"):
                from PIL import ImageOps

                img = ImageOps.exif_transpose(img)

            # Resize if larger than max dimension
            if max(img.size) > _MAX_IMAGE_DIMENSION:
                resampling = getattr(Image, "Resampling", Image)
                img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION), resampling.LANCZOS)

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
                    len(file_data),
                    len(compressed),
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
        """Return (file_bytes, content_type, filename) from disk.

        Kept for backwards compatibility; prefer :meth:`get_file_path` which
        avoids loading the whole file into memory.
        """
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        content_type = self._content_type_from_ext(media.storage_path, media.media_type)
        # Serve WebP content type for converted images
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return full_path.read_bytes(), content_type, media.filename

    async def get_file_path(self, media_id: int) -> tuple[Path, str, str]:
        """Return (disk_path, content_type, filename) for streaming.

        Used by the download endpoint so the file is served directly from disk
        with HTTP range support (required for video/audio playback & seeking).
        """
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if not full_path.is_file():
            raise NotFoundError(f"Media file for {media_id} missing on disk")
        content_type = self._content_type_from_ext(media.storage_path, media.media_type)
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return full_path, content_type, media.filename

    async def delete(self, media_id: int) -> None:
        """Delete media record and remove file from disk."""
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if full_path.exists():
            full_path.unlink()
        await self.db.delete(media)
        await self.db.commit()

    async def list_for_entry(self, entry_id: int) -> list[Media]:
        """Return all media attachments for an entry."""
        result = await self.db.execute(
            select(Media).where(Media.entry_id == entry_id).order_by(Media.created_at)
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        media_type: str | None = None,
    ) -> tuple[list[tuple[Media, str, str | None]], int]:
        """Return all media across non-deleted entries, with entry context.

        Returns list of (media, entry_date_str, entry_title) tuples and total count.
        """
        base_q = (
            select(Media, Entry.entry_date, Entry.title)
            .join(Entry, Media.entry_id == Entry.id)
            .where(Entry.is_deleted == False)  # noqa: E712
        )
        if media_type:
            base_q = base_q.where(Media.media_type == media_type)

        # Total count
        count_q = select(func.count()).select_from(
            select(Media.id)
            .join(Entry, Media.entry_id == Entry.id)
            .where(Entry.is_deleted == False)  # noqa: E712
            .subquery()
        )
        if media_type:
            count_q = select(func.count()).select_from(
                select(Media.id)
                .join(Entry, Media.entry_id == Entry.id)
                .where(Entry.is_deleted == False, Media.media_type == media_type)  # noqa: E712
                .subquery()
            )
        total = (await self.db.execute(count_q)).scalar_one()

        # Paginated results
        rows = await self.db.execute(
            base_q.order_by(Media.created_at.desc()).offset(offset).limit(limit)
        )
        return [(m, str(date), title) for m, date, title in rows.all()], total

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
        """Return a MIME type hint for the media category.

        Accepts either a bare category ("audio") or a full MIME ("audio/webm")
        so the fallback is always a playable type rather than octet-stream.
        """
        category = media_type.split("/", 1)[0]  # "audio/webm" -> "audio"
        return {"image": "image/jpeg", "video": "video/mp4", "audio": "audio/mpeg"}.get(
            category, "application/octet-stream"
        )

    @staticmethod
    def _content_type_from_ext(storage_path: str, media_type: str) -> str:
        """Return accurate MIME type based on actual file extension.

        ``media_type`` may be either a bare category ("audio") or a full MIME
        ("audio/webm") depending on the upload path, so we normalise to the
        category prefix before mapping. Serving e.g. a .webm recording as
        ``audio/mpeg`` makes browsers refuse to play it, which is the bug this
        guards against.
        """
        ext = storage_path.rsplit(".", 1)[-1].lower() if "." in storage_path else ""
        category = media_type.split("/", 1)[0]  # "audio/webm" -> "audio"
        # Normalise legacy/variant MIME spellings to canonical playable ones.
        if media_type in ("audio/x-wav", "audio/wav", "audio/wave"):
            return "audio/wav"
        audio_map = {
            "webm": "audio/webm", "ogg": "audio/ogg", "mp3": "audio/mpeg",
            "mp4": "audio/mp4", "wav": "audio/wav", "m4a": "audio/mp4",
            "opus": "audio/opus",
        }
        if category == "audio" and ext in audio_map:
            return audio_map[ext]
        return MediaService._media_content_type(media_type)
