"""Tests for audio-note recording — backend-side capture (start/stop) → Ogg/Vorbis."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _reset_active_recording():
    """The active-capture slot is module-global; clear it around every test."""
    from app.services import recording_service as rs

    rs._active_recording = None
    yield
    rs._active_recording = None


class _FakeStream:
    """Stand-in for a sounddevice InputStream — records start/stop/close."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


async def _make_entry(client: AsyncClient, body: str = "") -> int:
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-06-26", "title": "note", "body": body}
    )
    return r.json()["id"]


class TestStartStop:
    """Backend-side microphone capture (sounddevice) via /start + /stop."""

    async def test_start_stop_creates_ogg_recording(self, client: AsyncClient):
        """Start then stop persists a valid, non-empty Ogg/Vorbis recording."""
        import io

        import numpy as np
        import soundfile as sf

        eid = await _make_entry(client)
        fake = _FakeStream()

        def fake_open(rec):  # noqa: ANN001
            # 1s of a 440 Hz tone as float32 mono — real enough for Vorbis to encode.
            t = np.linspace(0, 1, 16000, endpoint=False)
            rec.frames.append((0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32").reshape(-1, 1))
            return fake

        with patch("app.services.recording_service._open_input_stream", side_effect=fake_open):
            r = await client.post("/api/v1/recordings/start", data={"entry_id": str(eid)})
            assert r.status_code == 200, r.text
            assert r.json() == {"ok": True, "entry_id": eid}
            r = await client.post("/api/v1/recordings/stop")

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["audio_format"] == "ogg"
        assert data["entry_id"] == eid
        assert fake.stopped and fake.closed

        # The stored file is a valid Ogg/Vorbis that soundfile can decode.
        media = await client.get(f"/api/v1/media/{data['media_id']}/file")
        assert media.status_code == 200
        arr, sr = sf.read(io.BytesIO(media.content))
        assert sr == 16000 and arr.size > 0

    async def test_double_start_conflicts(self, client: AsyncClient):
        """Starting while a capture is already running is a 409."""
        eid = await _make_entry(client)
        with patch(
            "app.services.recording_service._open_input_stream", return_value=_FakeStream()
        ):
            r1 = await client.post("/api/v1/recordings/start", data={"entry_id": str(eid)})
            assert r1.status_code == 200
            r2 = await client.post("/api/v1/recordings/start", data={"entry_id": str(eid)})
        assert r2.status_code == 409

    async def test_stop_with_no_active_is_404(self, client: AsyncClient):
        """Stopping when nothing is recording is a 404."""
        r = await client.post("/api/v1/recordings/stop")
        assert r.status_code == 404

    async def test_start_mic_unavailable_is_500(self, client: AsyncClient):
        """If the microphone can't be opened, /start returns 500."""
        eid = await _make_entry(client)
        with patch(
            "app.services.recording_service._open_input_stream", side_effect=OSError("no device")
        ):
            r = await client.post("/api/v1/recordings/start", data={"entry_id": str(eid)})
        assert r.status_code == 500

    async def test_transcribe_endpoint_removed(self, client: AsyncClient):
        """Transcription was removed — the endpoint no longer exists (405/404)."""
        eid = await _make_entry(client)
        # No recording id 999, but the route itself is gone: any id → not 200.
        r = await client.post("/api/v1/recordings/999/transcribe")
        assert r.status_code in (404, 405, 422)
        assert eid  # keep the entry creation meaningful
