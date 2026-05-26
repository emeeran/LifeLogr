"""Business logic for voice recordings."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entry import Entry
from app.models.recording import VoiceRecording
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)

# Lazy-loaded Whisper model singleton
_whisper_model = None


def _get_whisper_model() -> Any:
    """Lazy-load the faster-whisper model on first transcription call."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        logger.info(
            "Loading Whisper model '%s' on device '%s'...",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
        )
        _whisper_model = WhisperModel(
            settings.WHISPER_MODEL, device=settings.WHISPER_DEVICE, compute_type="int8"
        )
        logger.info("Whisper model loaded.")
    return _whisper_model


class VoiceRecordingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.media_svc = MediaService(db)

    async def upload(self, entry_id: int, filename: str, file_data: bytes) -> VoiceRecording:
        """Store audio file, create media + recording records."""
        entry_result = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        if not entry_result.scalar_one_or_none():
            raise NotFoundError(f"Entry {entry_id} not found")

        audio_format = self._detect_format(filename)
        media = await self.media_svc.upload(entry_id, filename, f"audio/{audio_format}", file_data)

        recording = VoiceRecording(
            entry_id=entry_id,
            media_id=media.id,
            duration_seconds=0.0,
            audio_format=audio_format,
        )
        self.db.add(recording)
        await self.db.commit()
        await self.db.refresh(recording)
        return recording

    async def get(self, recording_id: int) -> VoiceRecording:
        """Return recording metadata."""
        result = await self.db.execute(
            select(VoiceRecording).where(VoiceRecording.id == recording_id)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            raise NotFoundError(f"Recording {recording_id} not found")
        return rec

    async def transcribe(self, recording_id: int) -> VoiceRecording:
        """Run local speech-to-text; append transcription to entry body."""
        rec = await self.get(recording_id)
        if rec.is_transcribed:
            raise ConflictError(f"Recording {recording_id} already transcribed")

        audio_bytes, _, _ = await self.media_svc.get_file(rec.media_id)
        text = self._run_stt(audio_bytes)
        rec.transcription = text
        rec.is_transcribed = True

        # Append transcription to entry body
        entry_result = await self.db.execute(select(Entry).where(Entry.id == rec.entry_id))
        entry = entry_result.scalar_one()
        entry.body += f"\n\n[Transcription]\n{text}"
        await self.db.commit()
        await self.db.refresh(rec)
        return rec

    async def delete(self, recording_id: int) -> None:
        """Delete recording and associated media."""
        rec = await self.get(recording_id)
        media_id = rec.media_id
        await self.db.delete(rec)
        await self.db.flush()
        # Delete media file + record in a fresh session context
        await self.media_svc.delete(media_id)

    @staticmethod
    def _detect_format(filename: str) -> str:
        """Detect audio format from filename extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"
        return ext if ext in ("mp3", "mp4") else "mp3"

    @staticmethod
    def _run_stt(audio_data: bytes) -> str:
        """Run local speech-to-text using faster-whisper."""
        try:
            model = _get_whisper_model()
        except Exception as exc:
            logger.error("Failed to load Whisper model: %s", exc)
            raise RuntimeError(f"Speech-to-text unavailable: {exc}") from exc

        # Write audio to a temp file (faster-whisper needs a file path)
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            segments, _info = model.transcribe(tmp_path, beam_size=5)
            text = " ".join(segment.text.strip() for segment in segments)
            return text
        finally:
            Path(tmp_path).unlink(missing_ok=True)
