"""Tests for voice recording transcription — STT + resilient body append."""

from unittest.mock import patch

from httpx import AsyncClient


async def _make_recording(client: AsyncClient) -> dict:
    """Create an entry + a recording and return the recording payload."""
    import io
    import wave

    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-06-25", "title": "stt", "body": ""}
    )
    entry_id = r.json()["id"]

    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(b"\x00\x00" * 16000)  # 1s silence
    w.close()

    r = await client.post(
        "/api/v1/recordings",
        files={"file": ("r.wav", buf.getvalue(), "audio/wav")},
        data={"entry_id": str(entry_id)},
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestTranscribe:
    async def test_transcribe_succeeds_and_sets_text(self, client: AsyncClient):
        """A successful STT run marks the recording transcribed with text."""
        rec = await _make_recording(client)

        with patch("app.services.recording_service._get_whisper_model") as mock_model:
            # Stub a model whose transcribe() yields one segment.
            class _Seg:
                def __init__(self, t: str) -> None:
                    self.text = t
            mock_model.return_value.transcribe.return_value = (
                [_Seg("hello world")],
                None,
            )

            r = await client.post(f"/api/v1/recordings/{rec['id']}/transcribe")

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_transcribed"] is True
        assert "hello world" in data["transcription"]

    async def test_transcribe_survives_body_append_failure(self, client: AsyncClient):
        """If the entry body append fails (e.g. FTS trigger), the transcription
        is still saved on the recording — never lost."""
        rec = await _make_recording(client)

        with (
            patch("app.services.recording_service._get_whisper_model") as mock_model,
            patch(
                "app.services.recording_service.VoiceRecordingService"
                "._append_transcription_to_entry",
                side_effect=RuntimeError("FTS SQL logic error"),
            ),
        ):
            class _Seg:
                def __init__(self, t: str) -> None:
                    self.text = t
            mock_model.return_value.transcribe.return_value = ([_Seg("survived")], None)

            r = await client.post(f"/api/v1/recordings/{rec['id']}/transcribe")

        # Body append failed, but transcribe still returns 200 with the text.
        assert r.status_code == 200, r.text
        assert r.json()["is_transcribed"] is True
        assert "survived" in r.json()["transcription"]

    async def test_transcribe_twice_conflicts(self, client: AsyncClient):
        """Re-transcribing an already-transcribed recording is a 409."""
        rec = await _make_recording(client)
        with patch("app.services.recording_service._get_whisper_model") as mock_model:
            class _Seg:
                def __init__(self, t: str) -> None:
                    self.text = t
            mock_model.return_value.transcribe.return_value = ([_Seg("one")], None)
            await client.post(f"/api/v1/recordings/{rec['id']}/transcribe")
            r = await client.post(f"/api/v1/recordings/{rec['id']}/transcribe")
        assert r.status_code == 409
