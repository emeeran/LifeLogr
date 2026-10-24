"""Business logic for note-scoped media attachments.

Reuses the entry ``MediaService`` validation policy (allowed MIME prefixes,
blocked magic-number signatures) and its image-compression/content-type
helpers so the security and WebP behaviour is identical to entry media.
Files are stored under ``MEDIA_DIR/notes/``.
"""

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, NotFoundError
from app.models.note import Note
from app.models.note_media import NoteMedia
from app.services.media_service import (
    _ALLOWED_MIME_PREFIXES,
    _BLOCKED_SIGNATURES,
    _CONVERTIBLE_IMAGE_TYPES,
    MediaService,
    read_head,
    validate_import_path,
)

logger = logging.getLogger(__name__)


# Extension → MIME mapping for path-based imports (Tauri native drag-drop gives
# a path, not a browser MIME type). Unknown extensions are rejected by upload().
_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "svg": "image/svg+xml",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "txt": "text/plain",
}


class NoteMediaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upload(
        self,
        note_id: int,
        filename: str,
        content_type: str,
        file_data: bytes,
        caption: str | None = None,
    ) -> NoteMedia:
        """Store file on disk under MEDIA_DIR/notes/ and create a NoteMedia record."""
        if len(file_data) > settings.MAX_MEDIA_SIZE_BYTES:
            raise MediaSizeError(f"File exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")

        if not any(content_type.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
            raise MediaSizeError(f"File type '{content_type}' not allowed")

        for sig, label in _BLOCKED_SIGNATURES.items():
            if file_data[: len(sig)] == sig:
                logger.warning("Blocked upload of %s (detected %s)", filename, label)
                raise MediaSizeError(f"File type not allowed: detected {label}")

        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename:
            raise MediaSizeError("Invalid filename")

        await self._require_note(note_id)

        media_type = MediaService._classify_media(content_type)

        final_data = file_data
        final_ext = Path(safe_name).suffix or ".bin"
        if content_type in _CONVERTIBLE_IMAGE_TYPES:
            # PIL decode/resize/WebP-encode is CPU-bound — off the event loop.
            final_data, converted = await asyncio.to_thread(
                MediaService._compress_to_webp, file_data
            )
            if converted:
                final_ext = ".webp"

        stored_name = f"{uuid.uuid4()}{final_ext}"
        rel_path = f"notes/{stored_name}"
        full_path = settings.MEDIA_DIR / "notes" / stored_name
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(full_path.write_bytes, final_data)

        media = NoteMedia(
            note_id=note_id,
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

    async def upload_file(
        self,
        note_id: int,
        filename: str,
        content_type: str,
        src: Path,
        caption: str | None = None,
        size: int | None = None,
    ) -> NoteMedia:
        """Store an already-spooled upload under MEDIA_DIR/notes/.

        Streaming counterpart of :meth:`upload`: the router hands over the temp
        file it spooled with :func:`media_service.spool_upload`, so an oversized
        payload is rejected without ever being held in memory.
        """
        if size is None:
            size = (await asyncio.to_thread(src.stat)).st_size
        if size > settings.MAX_MEDIA_SIZE_BYTES:
            raise MediaSizeError(f"File exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")
        if not any(content_type.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
            raise MediaSizeError(f"File type '{content_type}' not allowed")
        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename:
            raise MediaSizeError("Invalid filename")

        head = await asyncio.to_thread(read_head, src)
        for sig, label in _BLOCKED_SIGNATURES.items():
            if head[: len(sig)] == sig:
                logger.warning("Blocked upload of %s (detected %s)", filename, label)
                raise MediaSizeError(f"File type not allowed: detected {label}")

        await self._require_note(note_id)

        media_type = MediaService._classify_media(content_type)
        final_ext = Path(safe_name).suffix or ".bin"

        final_data: bytes | None = None
        if content_type in _CONVERTIBLE_IMAGE_TYPES:
            data = await asyncio.to_thread(src.read_bytes)
            final_data, converted = await asyncio.to_thread(MediaService._compress_to_webp, data)
            if converted:
                final_ext = ".webp"

        stored_name = f"{uuid.uuid4()}{final_ext}"
        rel_path = f"notes/{stored_name}"
        full_path = settings.MEDIA_DIR / "notes" / stored_name
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        if final_data is not None:
            file_size = len(final_data)
            await asyncio.to_thread(full_path.write_bytes, final_data)
        else:
            file_size = size
            await asyncio.to_thread(shutil.move, str(src), str(full_path))

        media = NoteMedia(
            note_id=note_id,
            filename=safe_name,
            media_type=media_type,
            file_size=file_size,
            storage_path=rel_path,
            caption=caption,
        )
        self.db.add(media)
        await self.db.commit()
        await self.db.refresh(media)
        return media

    async def _require_note(self, note_id: int) -> None:
        note = (
            await self.db.execute(
                select(Note).where(Note.id == note_id, Note.is_deleted == False)  # noqa: E712
            )
        ).scalar_one_or_none()
        if not note:
            raise NotFoundError(f"Note {note_id} not found")


    async def upload_from_path(
        self, note_id: int, path: str, caption: str | None = None
    ) -> NoteMedia:
        """Read a local file by absolute path and import it as note media.

        Used by the Tauri native drag-drop handler (WebKitGTK doesn't deliver
        HTML5 file drops, so the frontend receives a path, not a File object).

        Sandboxed by the shared :func:`media_service.validate_import_path`
        allowlist — user space (standard folders + visible home folders) and the
        system temp dir, with sensitive locations (the app's own data dir,
        ~/.ssh, ~/.gnupg, ~/.config, any hidden folder under home) denied, so the
        unauthenticated endpoint can't be used to read arbitrary files.
        """
        p = validate_import_path(path)
        ext = p.suffix.lower().lstrip(".")
        content_type = _EXT_TO_MIME.get(ext, "application/octet-stream")
        data = await asyncio.to_thread(p.read_bytes)
        return await self.upload(note_id, p.name, content_type, data, caption)

    async def list_for_note(self, note_id: int) -> list[NoteMedia]:
        result = await self.db.execute(
            select(NoteMedia).where(NoteMedia.note_id == note_id).order_by(NoteMedia.created_at)
        )
        return list(result.scalars().all())

    async def _get_owned(self, media_id: int, note_id: int) -> NoteMedia:
        result = await self.db.execute(
            select(NoteMedia).where(NoteMedia.id == media_id, NoteMedia.note_id == note_id)
        )
        media = result.scalar_one_or_none()
        if not media:
            raise NotFoundError(f"Note media {media_id} not found")
        return media

    async def get_file_path(self, media_id: int, note_id: int) -> tuple[Path, str, str]:
        """Return (disk_path, content_type, filename) for streaming."""
        media = await self._get_owned(media_id, note_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if not full_path.is_file():
            raise NotFoundError(f"Media file for {media_id} missing on disk")
        content_type = MediaService._content_type_from_ext(media.storage_path, media.media_type)
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return full_path, content_type, media.filename

    async def delete(self, media_id: int, note_id: int) -> None:
        media = await self._get_owned(media_id, note_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if full_path.exists():
            full_path.unlink()
        await self.db.delete(media)
        await self.db.commit()
