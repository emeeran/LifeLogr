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
from app.models.recording import VoiceRecording
from app.services.entry_service import get_entry_or_raise
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)

# ── Live microphone capture (backend sidecar) ───────────────────────────────
# Audio notes are captured here in the backend process via sounddevice/PortAudio
# (PulseAudio/ALSA), not the webview's MediaRecorder, which is unreliable in the
# packaged WebKit2GTK build (0-byte files). Captures are conditioned (rumble
# high-pass + speech-level normalisation) and encoded to Ogg/Vorbis on stop —
# full-rate capture with Vorbis compression keeps files reasonable.

_RECORD_SAMPLE_RATE = 44100  # full-rate capture; avoids harsh device resampling
_RECORD_CHANNELS = 1

# Speech-level normalisation: cheap mics often record far too quiet, so the
# capture is brought up to a spoken-voice RMS (~ -20 dBFS). The gain is capped
# so the preamp noise floor of a near-silent capture isn't turned into hiss.
_TARGET_RMS = 0.10
_MAX_GAIN = 4.0
# One-pole-style high-pass (implemented via FFT fade-in below cutoff) removes
# DC offset and desk/handling rumble that a lap or handheld mic picks up.
_HIGHPASS_CUTOFF_HZ = 90.0

# ── Stationary-noise reduction (spectral gate) ──────────────────────────────
# Mic preamp hiss / fan noise is broadband and stationary, so a per-bin noise
# floor estimated from the quietest frames can be subtracted in the spectral
# domain without touching speech pauses' *shape*. Two choices keep it artifact
# -free: the floor is smoothed across frequency (a narrow tonal peak — voice
# fundamentals, sirens — rides above its smeared broadband floor, so it is
# never mistaken for noise), and gains are smoothed over time (no "musical
# noise" twinkle between frames).
_GATE_FRAME = 2048  # ~46 ms at 44.1 kHz
_GATE_HOP = 512  # 75% overlap — COLA for the Hann window
_GATE_MIN_SECONDS = 1.0  # shorter captures have no stable noise profile
_GATE_OVERSUBTRACT = 2.0  # subtract twice the estimated floor
_GATE_FLOOR_DB = -20.0  # max attenuation — a hard floor sounds less artificial
_GATE_SMOOTH_BINS = 4  # ±4 bins (~±86 Hz) frequency smear of the noise floor
_GATE_TIME_ALPHA = 0.4  # one-pole temporal smoothing of per-bin gains


def _spectral_gate(audio: Any, rate: int) -> Any:
    """Reduce stationary broadband noise in a float32 (n, 1) block."""
    import numpy as np

    n = audio.shape[0]
    if n < max(_GATE_FRAME * 2, int(_GATE_MIN_SECONDS * rate)):
        return audio  # too short for a stable noise profile — leave it alone

    x = audio[:, 0].astype(np.float64)
    # Zero-pad by one frame each side: spectral modification breaks the
    # exact per-sample reconstruction at the OLA edges where the window
    # sum is tiny, and dividing by it there explodes. Padding puts every
    # real sample in the fully-overlapped interior (window sum ≈ 1.5);
    # the padded edges, where reconstruction is rough, are cropped away.
    pad = _GATE_FRAME
    xp = np.concatenate([np.zeros(pad), x, np.zeros(pad)])
    win = np.hanning(_GATE_FRAME)
    frames = 1 + (xp.size - _GATE_FRAME) // _GATE_HOP
    starts = np.arange(frames) * _GATE_HOP
    idx = starts[:, None] + np.arange(_GATE_FRAME)[None, :]
    spec = np.fft.rfft(xp[idx] * win, axis=1)  # (frames, bins)
    mag = np.abs(spec)

    # Noise floor: per-bin 10th percentile across frames — pauses and
    # quiet frames dominate the estimate, speech barely moves it.
    floor = np.percentile(mag, 10, axis=0)
    # Smear the floor across ±_GATE_SMOOTH_BINS: broadband hiss keeps its
    # level, a narrow tonal peak keeps the bins near it near zero, so the
    # floor under the peak collapses and the peak survives the subtraction.
    kernel = np.ones(2 * _GATE_SMOOTH_BINS + 1)
    floor = np.convolve(floor, kernel / kernel.size, mode="same")

    # Wiener-style subtraction gain, clamped so attenuation bottoms out.
    gain = np.clip(
        (mag - _GATE_OVERSUBTRACT * floor[None, :]) / np.maximum(mag, 1e-12),
        10.0 ** (_GATE_FLOOR_DB / 20.0),
        1.0,
    )
    # Temporal one-pole on the gains — hides frame-to-frame twinkle.
    for f in range(1, frames):
        gain[f] = _GATE_TIME_ALPHA * gain[f] + (1.0 - _GATE_TIME_ALPHA) * gain[f - 1]

    shaped = (np.fft.irfft(spec * gain, axis=1) * win).astype(np.float64)

    # Overlap-add and divide by the per-sample window-energy sum (Hann² at
    # 75% overlap is constant across the interior; the padded edges — where
    # it isn't — are cropped below).
    out = np.zeros(xp.size)
    norm = np.zeros(xp.size)
    for f in range(frames):
        s = starts[f]
        out[s : s + _GATE_FRAME] += shaped[f]
        norm[s : s + _GATE_FRAME] += win**2
    out = out / np.maximum(norm, 1e-6)
    return out[pad : pad + n].astype(np.float32)[:, None]


def _condition_audio(audio: Any, rate: int) -> Any:
    """Denoise + high-pass + normalise a captured float32 (n, 1) block."""
    import numpy as np

    if audio.size == 0:
        return audio

    # High-pass: linear gain fade-in below the cutoff (gentle, not a brick
    # wall) — zeroes DC while keeping the voice band untouched.
    n = audio.shape[0]
    spec = np.fft.rfft(audio[:, 0].astype(np.float64))
    freqs = np.fft.rfftfreq(n, d=1.0 / rate)
    spec *= np.clip(freqs / _HIGHPASS_CUTOFF_HZ, 0.0, 1.0)
    out = np.fft.irfft(spec, n).astype(np.float32)[:, None]

    # Stationary-noise gate before level decisions: normalisation must measure
    # the *voice*, not the hiss it would otherwise amplify with it.
    out = _spectral_gate(out, rate)

    # Speech-level normalisation (RMS-targeted with a hard gain cap).
    rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))
    if rms < 1e-5:
        return out  # digital silence — nothing to scale
    gain = min(_TARGET_RMS / rms, _MAX_GAIN)
    if gain <= 1.0:
        return out
    return np.clip(out * np.float32(gain), np.float32(-1.0), np.float32(1.0))


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
    """Open and start a full-rate mono float32 InputStream on the default mic.

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
        # Generous, stable buffers — priority is drop-free capture, not latency.
        blocksize=0,
        latency="high",
        callback=_on_chunk,
    )
    stream.start()
    return stream


def _frames_to_ogg(frames: list[Any], rate: int) -> bytes:
    """Condition captured float32 frames and encode to Ogg/Vorbis in memory."""
    import numpy as np
    import soundfile as sf  # type: ignore[import-untyped]

    audio = np.concatenate(frames, axis=0) if frames else np.empty((0, 1), dtype="float32")
    audio = _condition_audio(audio, rate)
    buf = io.BytesIO()
    # libsndfile writes Ogg/Vorbis — Vorbis compression keeps full-rate mono
    # captures compact (~0.5 MB/min).
    sf.write(buf, audio, rate, format="OGG", subtype="VORBIS")
    return buf.getvalue()


class VoiceRecordingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.media_svc = MediaService(db)

    async def upload(self, entry_id: int, filename: str, file_data: bytes) -> VoiceRecording:
        """Store an audio file, create media + recording records."""
        await get_entry_or_raise(self.db, entry_id, include_deleted=True)

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
        await get_entry_or_raise(self.db, entry_id, include_deleted=True)

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
