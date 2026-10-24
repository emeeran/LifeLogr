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


# Minimal PNG (1×1) — same stub the notes from-path tests use.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0f01f0005000105ab5e30"
    "5f0000000049454e44ae426082"
)


class TestMediaFromPath:
    """POST /media/from-path — Tauri drag-drop import for the journal editor.

    Sandbox contract mirrors the notes variant: home dir + temp only,
    sensitive locations denied.
    """

    async def test_import_png_from_tmp(self, client: AsyncClient, tmp_path):
        entry = await _entry(client)
        f = tmp_path / "pic.png"
        f.write_bytes(_PNG_1x1)
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": str(f)},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "image"
        assert r.json()["entry_id"] == entry["id"]

    async def test_import_video_from_tmp(self, client: AsyncClient, tmp_path):
        entry = await _entry(client)
        f = tmp_path / "clip.mp4"
        # Minimal MP4 header bytes (ftyp box) — enough to pass magic checks.
        f.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": str(f)},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "video"

    async def test_missing_path_returns_404(self, client: AsyncClient):
        entry = await _entry(client)
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": "/nonexistent/file.png"},
        )
        assert r.status_code == 404

    async def test_outside_home_rejected(self, client: AsyncClient, monkeypatch, tmp_path):
        import app.services.media_service as ms

        entry = await _entry(client)
        # Simulate a file that resolves outside home+temp (e.g. /etc/hostname).
        monkeypatch.setattr(ms.Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr(ms.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
        f = tmp_path / "elsewhere.png"
        f.write_bytes(_PNG_1x1)
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": "/etc/hostname"},
        )
        assert r.status_code in (400, 403, 404, 422)

    async def test_sensitive_dir_rejected(self, client: AsyncClient, tmp_path):
        from pathlib import Path

        from app.core.exceptions import ValidationError
        from app.services.media_service import MediaService
        from app.core.database import async_session

        entry = await _entry(client)
        secret = Path.home() / ".ssh" / "authorized_keys"
        async with async_session() as session:
            with __import__("pytest").raises(ValidationError):
                await MediaService(session).upload_from_path(entry["id"], str(secret))

    async def test_unknown_extension_rejected(self, client: AsyncClient, tmp_path):
        entry = await _entry(client)
        f = tmp_path / "blob.zzz"
        f.write_bytes(b"random bytes")
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": str(f)},
        )
        assert r.status_code == 400

    async def test_blocked_signature_rejected(self, client: AsyncClient, tmp_path):
        entry = await _entry(client)
        f = tmp_path / "evil.png"
        f.write_bytes(b"MZ\x90\x00")  # Windows executable magic
        r = await client.post(
            "/api/v1/media/from-path",
            json={"entry_id": entry["id"], "path": str(f)},
        )
        assert r.status_code == 400
