"""Business logic for voice/audio-note recordings."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entry import Entry
from app.models.recording import VoiceRecording
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)

# ── Live microphone capture (backend sidecar) ───────────────────────────────
# Audio notes are captured here in the backend process via sounddevice/PortAudio
# (PulseAudio/ALSA), not the webview's MediaRecorder, which is unreliable in the
# packaged WebKit2GTK build (0-byte files). Captures are encoded to Ogg/Vorbis
# on stop — ~7-10× smaller than raw WAV at voice quality.

_RECORD_SAMPLE_RATE = 16000  # voice-quality; keeps files compact
_RECORD_CHANNELS = 1


class _LiveRecording:
    """A single in-progress microphone capture (not DB-backed)."""

    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        self.frames: list[Any] = []
        self.stream: Any = None
        self.lock = threading.Lock()


# One active capture at a time — the desktop app is single-user.
_active_recording: _LiveRecording | None = None
_active_lock = threading.Lock()


def _open_input_stream(rec: _LiveRecording) -> Any:
    """Open and start a 16kHz mono float32 InputStream on the default mic.

    sounddevice is imported lazily so the module (and the app) still load when
    the library is absent; the failure is surfaced only when recording starts.
    """
    import sounddevice as sd  # type: ignore[import-untyped]

    def _on_chunk(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        # Runs on PortAudio's audio thread — just buffer the float32 samples.
        with rec.lock:
            rec.frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=_RECORD_SAMPLE_RATE,
        channels=_RECORD_CHANNELS,
        dtype="float32",
        callback=_on_chunk,
    )
    stream.start()
    return stream


def _frames_to_ogg(frames: list[Any], rate: int) -> bytes:
    """Encode captured float32 frames into an Ogg/Vorbis stream in memory."""
    import numpy as np
    import soundfile as sf  # type: ignore[import-untyped]

    audio = np.concatenate(frames, axis=0) if frames else np.empty((0, 1), dtype="float32")
    buf = io.BytesIO()
    # libsndfile writes Ogg/Vorbis — ~7-10× smaller than WAV, voice-quality.
    sf.write(buf, audio, rate, format="OGG", subtype="VORBIS")
    return buf.getvalue()


class VoiceRecordingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.media_svc = MediaService(db)

    async def upload(self, entry_id: int, filename: str, file_data: bytes) -> VoiceRecording:
        """Store an audio file, create media + recording records."""
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

    async def start_recording(self, entry_id: int) -> None:
        """Begin capturing the default microphone for an entry."""
        global _active_recording
        entry_result = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        if not entry_result.scalar_one_or_none():
            raise NotFoundError(f"Entry {entry_id} not found")

        with _active_lock:
            if _active_recording is not None:
                raise ConflictError("A recording is already in progress")
            rec = _LiveRecording(entry_id)
            try:
                rec.stream = await asyncio.to_thread(_open_input_stream, rec)
            except Exception as exc:
                logger.error("Failed to open microphone: %s", exc)
                raise RuntimeError(f"Could not open microphone: {exc}") from exc
            _active_recording = rec

    async def stop_recording(self) -> VoiceRecording:
        """Stop the active capture, encode it to Ogg/Vorbis, and persist it."""
        global _active_recording
        with _active_lock:
            rec = _active_recording
            _active_recording = None
        if rec is None:
            raise NotFoundError("No active recording")

        if rec.stream is not None:
            try:
                await asyncio.to_thread(rec.stream.stop)
                await asyncio.to_thread(rec.stream.close)
            except Exception:
                logger.warning("Error stopping audio stream", exc_info=True)

        with rec.lock:
            frames = list(rec.frames)
        if not frames:
            raise RuntimeError(
                "No audio was captured. Check that a microphone is connected and "
                "not in use by another app, then try again."
            )

        ogg_bytes = await asyncio.to_thread(_frames_to_ogg, frames, _RECORD_SAMPLE_RATE)
        # A real Vorbis capture is at least a few hundred bytes; anything tiny
        # means effectively nothing was captured.
        if len(ogg_bytes) < 200:
            raise RuntimeError(
                "No audio was captured. Check that a microphone is connected and "
                "not in use by another app, then try again."
            )

        media = await self.media_svc.upload(rec.entry_id, "recording.ogg", "audio/ogg", ogg_bytes)
        recording = VoiceRecording(
            entry_id=rec.entry_id,
            media_id=media.id,
            duration_seconds=0.0,
            audio_format="ogg",
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
