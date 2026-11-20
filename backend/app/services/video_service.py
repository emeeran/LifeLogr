"""VideoService — upload, thumbnail, and delete video notes."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, NotFoundError
from app.models.video_note import VideoNote
from app.services import media_crypto
from app.services.entry_service import get_entry_or_raise
from app.services.media_service import (
    check_signature,
    ensure_within_media_cap,
    read_head,
    unlink_media_file,
)

logger = logging.getLogger(__name__)


def _require_video_mime(content_type: str) -> None:
    if not content_type.startswith("video/"):
        raise MediaSizeError(
            f"File type '{content_type}' not allowed; only video/* is accepted"
        )


def _storage_name(entry_id: int, filename: str) -> str:
    ext = Path(filename).suffix or ".mp4"
    return f"videos/{entry_id}/{uuid.uuid4().hex}{ext}"


class VideoService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._media_dir = Path(settings.MEDIA_DIR)

    async def _create_note(
        self, entry_id: int, filename: str, storage_name: str
    ) -> VideoNote:
        note = VideoNote(
            entry_id=entry_id,
            filename=filename,
            storage_path=storage_name,
        )
        self.db.add(note)
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def upload(
        self, entry_id: int, filename: str, content_type: str, data: bytes
    ) -> VideoNote:
        """Upload a video file and create a VideoNote record."""
        entry = await get_entry_or_raise(self.db, entry_id)

        ensure_within_media_cap(len(data))
        _require_video_mime(content_type)
        check_signature(data, filename)

        storage_name = _storage_name(entry_id, filename)
        storage_path = self._media_dir / storage_name
        # Writing a clip of up to 25 MB is file I/O — keep it off the event loop.
        await asyncio.to_thread(storage_path.parent.mkdir, parents=True, exist_ok=True)
        if entry.is_encrypted and settings.ENCRYPT_MEDIA:
            # Third attachment store, same at-rest rule as media/note media
            # (docs/design/media-encryption.md §5) — clips of encrypted entries
            # must not sit in the clear under MEDIA_DIR/videos.
            data = await asyncio.to_thread(media_crypto.encrypt_media, data, storage_name)
        await asyncio.to_thread(storage_path.write_bytes, data)
        return await self._create_note(entry_id, filename, storage_name)

    async def upload_file(
        self, entry_id: int, filename: str, content_type: str, src: Path
    ) -> VideoNote:
        """Store an already-spooled upload and create the VideoNote record.

        The streaming router hands over the temp file it spooled, so an oversized
        video is rejected without ever being held in memory. The spool file is
        consumed (moved) on success — the caller still unlinks it, which is a
        safe no-op afterwards.
        """
        entry = await get_entry_or_raise(self.db, entry_id)

        size = (await asyncio.to_thread(src.stat)).st_size
        ensure_within_media_cap(size)
        _require_video_mime(content_type)
        check_signature(await asyncio.to_thread(read_head, src), filename)

        storage_name = _storage_name(entry_id, filename)
        storage_path = self._media_dir / storage_name
        await asyncio.to_thread(storage_path.parent.mkdir, parents=True, exist_ok=True)
        if entry.is_encrypted and settings.ENCRYPT_MEDIA:
            data = await asyncio.to_thread(src.read_bytes)
            data = await asyncio.to_thread(media_crypto.encrypt_media, data, storage_name)
            await asyncio.to_thread(storage_path.write_bytes, data)
        else:
            await asyncio.to_thread(shutil.move, str(src), str(storage_path))
        return await self._create_note(entry_id, filename, storage_name)

    async def get(self, video_id: int) -> VideoNote:
        result = await self.db.execute(select(VideoNote).where(VideoNote.id == video_id))
        note = result.scalar_one_or_none()
        if not note:
            raise NotFoundError(f"Video note {video_id} not found")
        return note

    async def list_for_entry(self, entry_id: int) -> list[VideoNote]:
        await get_entry_or_raise(self.db, entry_id)
        result = await self.db.execute(
            select(VideoNote).where(VideoNote.entry_id == entry_id).order_by(VideoNote.created_at)
        )
        return list(result.scalars().all())

    async def delete(self, video_id: int) -> None:
        """Delete a video note, then remove its file from disk."""
        note = await self.get(video_id)
        file_path = self._media_dir / note.storage_path
        await self.db.delete(note)
        await self.db.commit()
        # Unlink only after the commit (same ordering rule as
        # EntryService.purge).
        unlink_media_file(file_path, context="video note")

    def get_file_path(self, note: VideoNote) -> Path:
        """Return the filesystem path to the video file."""
        return self._media_dir / note.storage_path
