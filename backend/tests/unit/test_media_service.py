"""Integration tests for media — upload, list, delete, classify."""

from httpx import AsyncClient


async def _entry(client: AsyncClient):
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "With media"}
    )
    return r.json()


class TestMediaClassify:
    async def test_classify_image(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "test"})
        assert r.status_code == 201
        # Media upload requires actual file — test classification helpers via service
        from app.services.media_service import MediaService

        assert MediaService._classify_media("image/png") == "image"
        assert MediaService._classify_media("video/mp4") == "video"
        assert MediaService._classify_media("audio/wav") == "audio"
        assert MediaService._classify_media("application/pdf") == "document"


class TestContentTypeFromExt:
    """Regression guard for the audio playback bug.

    Recordings are stored with media_type="audio/webm" (a full MIME, not the
    bare category "audio"). _content_type_from_ext must still resolve the
    correct MIME per extension; otherwise a .webm file served as audio/mpeg
    is rejected by the browser and won't play.
    """

    def test_webm_recording_served_as_audio_webm(self):
        from app.services.media_service import MediaService

        # media_type carries a full MIME from the recording upload path.
        assert MediaService._content_type_from_ext("rec-abc.webm", "audio/webm") == "audio/webm"

    def test_bare_audio_category_still_works(self):
        from app.services.media_service import MediaService

        assert MediaService._content_type_from_ext("song.mp3", "audio") == "audio/mpeg"
        assert MediaService._content_type_from_ext("clip.wav", "audio") == "audio/wav"

    def test_unknown_audio_ext_falls_back_to_mpeg(self):
        from app.services.media_service import MediaService

        assert MediaService._content_type_from_ext("track.xyz", "audio/xyz") == "audio/mpeg"

    def test_image_and_video_passthrough(self):
        from app.services.media_service import MediaService

        assert MediaService._content_type_from_ext("pic.webp", "image").startswith("image/")
        assert MediaService._content_type_from_ext("clip.mp4", "video").startswith("video/")


class TestWavContentType:
    """Webkit2GTK records WAV; ensure it's served with a playable MIME."""

    def test_wav_extension_served_as_audio_wav(self):
        from app.services.media_service import MediaService

        assert (
            MediaService._content_type_from_ext("rec.webm".replace("webm", "wav"), "audio/wav")
            == "audio/wav"
        )

    def test_legacy_x_wav_normalised(self):
        from app.services.media_service import MediaService

        assert MediaService._content_type_from_ext("old.wav", "audio/x-wav") == "audio/wav"
        assert MediaService._content_type_from_ext("old.wav", "audio/wave") == "audio/wav"
