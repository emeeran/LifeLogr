"""Business logic for voice recordings."""

from __future__ import annotations

import asyncio
import logging
import sys
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


def _bundled_whisper_path() -> Path | None:
    """Locate a build-time-bundled Whisper model directory, if present.

    The desktop build pre-downloads the model into ``backend/models/faster-whisper-<name>``
    and PyInstaller bundles it. In dev it lives under the repo root; in a frozen
    build it is extracted next to the executable. Returning a path here lets us
    transcribe fully offline with ``local_files_only=True``.
    """
    name = settings.WHISPER_MODEL
    candidates = [
        # Frozen (PyInstaller): bundled at <exe_dir>/models/...
        Path(sys.argv[0]).resolve().parent / "models" / f"faster-whisper-{name}",
        # Dev: <repo>/backend/models/...
        Path(__file__).resolve().parents[2] / "models" / f"faster-whisper-{name}",
    ]
    for p in candidates:
        if (p / "model.bin").is_file():
            return p
    return None


def _get_whisper_model() -> Any:
    """Lazy-load the faster-whisper model on first transcription call.

    Prefers a build-time-bundled model (offline, instant). Falls back to a
    network download only if no bundle is present (dev without the model
    staged).
    """
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "Speech-to-text requires faster-whisper. "
                'Install it with: uv pip install -e \".[stt]\"'
            ) from exc

        bundled = _bundled_whisper_path()
        source = bundled if bundled else settings.WHISPER_MODEL
        logger.info(
            "Loading Whisper model '%s' on device '%s'%s...",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
            " (bundled, offline)" if bundled else " (downloading on first use)",
        )
        _whisper_model = WhisperModel(
            str(source) if bundled else settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type="int8",
            local_files_only=bundled is not None,
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
        """Run local speech-to-text and persist the result on the recording.

        The recording record is the single source of truth for the spoken
        text. The entry *body* is the frontend editor's responsibility — the
        UI appends a ``[Transcription]`` block to the live editor (and
        autosaves) — so this method deliberately does NOT mutate the entry as
        a side-effect of transcription. (The text is never lost regardless of
        what the UI does: it is committed here on the recording.)
        """
        rec = await self.get(recording_id)
        if rec.is_transcribed:
            raise ConflictError(f"Recording {recording_id} already transcribed")

        audio_bytes, _, _ = await self.media_svc.get_file(rec.media_id)
        # Normalise: an empty/whitespace result means no speech was detected
        # (common with a silent recording). We mark the recording transcribed
        # either way; the frontend surfaces a "no speech detected" notice.
        text = (await asyncio.to_thread(self._run_stt, audio_bytes, rec.audio_format) or "").strip()

        rec.transcription = text
        rec.is_transcribed = True
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
        return ext if ext in ("mp3", "mp4", "webm", "ogg", "wav", "m4a", "opus") else "mp3"

    @staticmethod
    def _run_stt(audio_data: bytes | Path, audio_format: str = "webm") -> str:
        """Run local speech-to-text using faster-whisper from bytes or a file path."""
        try:
            model = _get_whisper_model()
        except Exception as exc:
            logger.error("Failed to load Whisper model: %s", exc)
            raise RuntimeError(f"Speech-to-text unavailable: {exc}") from exc

        if isinstance(audio_data, Path):
            segments, _info = model.transcribe(str(audio_data), beam_size=5)
            return " ".join(segment.text.strip() for segment in segments)

        # Use proper extension so faster-whisper can detect the codec
        allowed_exts = ("webm", "ogg", "wav", "mp3", "mp4", "m4a", "opus")
        suffix = f".{audio_format}" if audio_format in allowed_exts else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            segments, _info = model.transcribe(tmp_path, beam_size=5)
            text = " ".join(segment.text.strip() for segment in segments)
            return text
        finally:
            Path(tmp_path).unlink(missing_ok=True)
