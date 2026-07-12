"""VideoService — upload, thumbnail, and delete video notes."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, NotFoundError
from app.models.entry import Entry
from app.models.video_note import VideoNote
from app.services.media_service import _BLOCKED_SIGNATURES

logger = logging.getLogger(__name__)


class VideoService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._media_dir = Path(settings.MEDIA_DIR)

    async def _get_entry(self, entry_id: int) -> Entry:
        result = await self.db.execute(
            select(Entry).where(Entry.id == entry_id, Entry.is_deleted == False)  # noqa: E712
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found")
        return entry

    async def upload(
        self, entry_id: int, filename: str, content_type: str, data: bytes
    ) -> VideoNote:
        """Upload a video file and create a VideoNote record."""
        await self._get_entry(entry_id)

        if len(data) > settings.MAX_MEDIA_SIZE_BYTES:
            raise MediaSizeError(f"Video exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")
        if not content_type.startswith("video/"):
            raise MediaSizeError(
                f"File type '{content_type}' not allowed; only video/* is accepted"
            )
        for sig, label in _BLOCKED_SIGNATURES.items():
            if data[: len(sig)] == sig:
                logger.warning("Blocked video upload (detected %s)", label)
                raise MediaSizeError(f"File type not allowed: detected {label}")

        ext = Path(filename).suffix or ".mp4"
        storage_name = f"videos/{entry_id}/{uuid.uuid4().hex}{ext}"
        storage_path = self._media_dir / storage_name
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(data)

        note = VideoNote(
            entry_id=entry_id,
            filename=filename,
            storage_path=storage_name,
        )
        self.db.add(note)
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def get(self, video_id: int) -> VideoNote:
        result = await self.db.execute(select(VideoNote).where(VideoNote.id == video_id))
        note = result.scalar_one_or_none()
        if not note:
            raise NotFoundError(f"Video note {video_id} not found")
        return note

    async def list_for_entry(self, entry_id: int) -> list[VideoNote]:
        await self._get_entry(entry_id)
        result = await self.db.execute(
            select(VideoNote).where(VideoNote.entry_id == entry_id).order_by(VideoNote.created_at)
        )
        return list(result.scalars().all())

    async def delete(self, video_id: int) -> None:
        """Delete a video note and its file."""
        note = await self.get(video_id)
        file_path = self._media_dir / note.storage_path
        if file_path.exists():
            file_path.unlink()
        await self.db.delete(note)
        await self.db.commit()

    def get_file_path(self, note: VideoNote) -> Path:
        """Return the filesystem path to the video file."""
        return self._media_dir / note.storage_path
