"""End-to-end media encryption wiring (design note §12, wiring half).

Covers SEC-MEDIA-3: encrypt on upload for encrypted parents, decrypt on serve
(``/file`` with Range, ``/thumb``, OCR input), the 409 failure mode, and the
flag-only-gates-uploads rule. The codec itself is covered in
``tests/unit/test_media_crypto.py``.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.models.note import Note
from app.models.note_media import NoteMedia
from app.models.video_note import VideoNote
from app.services import media_crypto


def _png_bytes() -> bytes:
    """A real 4×4 red PNG so PIL thumbnail generation works."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _assert_same_image(served: bytes, original: bytes) -> None:
    """Uploads re-encode images to WebP (lossy) — compare size + channel means."""
    from PIL import Image, ImageStat

    a = Image.open(io.BytesIO(served)).convert("RGB")
    b = Image.open(io.BytesIO(original)).convert("RGB")
    assert a.size == b.size
    mean_a = ImageStat.Stat(a).mean
    mean_b = ImageStat.Stat(b).mean
    assert all(abs(x - y) < 5 for x, y in zip(mean_a, mean_b))


async def _encrypted_entry(db_session, *, encrypted: bool) -> Entry:
    entry = Entry(entry_date=date(2026, 3, 1), body="secret diary text", title="T")
    entry.is_encrypted = encrypted
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    return entry


async def _stored_path(db_session, media_id: int) -> Path:
    """On-disk path for a media record (MEDIA_DIR is shared across the session)."""
    media = (
        await db_session.execute(select(Media).where(Media.id == media_id))
    ).scalar_one()
    return settings.MEDIA_DIR / media.storage_path


@pytest.fixture
def encrypt_on(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPT_MEDIA", True)


async def test_flag_on_encrypts_upload_of_encrypted_entry(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201
    media = r.json()

    path = await _stored_path(db_session, media["id"])
    blob = path.read_bytes()
    assert media_crypto.is_encrypted(blob)
    assert media["file_size"] == len(blob)  # on-disk (ciphertext) size

    # Serving returns the plaintext (re-encoded to WebP by the normal upload
    # compression) with the right content type.
    r = await client.get(f"/api/v1/media/{media['id']}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    _assert_same_image(r.content, _png_bytes())


async def test_flag_on_keeps_plaintext_items_plaintext(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=False)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201
    blob = (await _stored_path(db_session, r.json()["id"])).read_bytes()
    assert not media_crypto.is_encrypted(blob)
    r = await client.get(f"/api/v1/media/{r.json()['id']}/file")
    assert r.status_code == 200
    _assert_same_image(r.content, _png_bytes())


async def test_flag_off_stores_plaintext_even_for_encrypted_entry(
    client: AsyncClient, db_session
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201
    blob = (await _stored_path(db_session, r.json()["id"])).read_bytes()
    assert not media_crypto.is_encrypted(blob)


async def test_range_requests_decrypt_only_the_requested_slice(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    payload = b"0123456789" * 1000  # 10 000 bytes of known plaintext
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("data.txt", payload, "text/plain")},  # not image → no re-encode
    )
    assert r.status_code == 201
    media_id = r.json()["id"]
    url = f"/api/v1/media/{media_id}/file"

    mid = await client.get(url, headers={"Range": "bytes=4990-5009"})
    assert mid.status_code == 206
    assert mid.content == payload[4990:5010]
    assert mid.headers["content-range"] == f"bytes 4990-5009/{len(payload)}"

    tail = await client.get(url, headers={"Range": "bytes=-100"})
    assert tail.status_code == 206
    assert tail.content == payload[-100:]

    open_ended = await client.get(url, headers={"Range": "bytes=9990-"})
    assert open_ended.status_code == 206
    assert open_ended.content == payload[9990:]

    bad = await client.get(url, headers={"Range": f"bytes={len(payload)}-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{len(payload)}"


async def test_tampered_blob_returns_409_and_file_is_untouched(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    media_id = r.json()["id"]
    path = await _stored_path(db_session, media_id)
    original = path.read_bytes()

    tampered = bytearray(original)
    tampered[len(tampered) // 2] ^= 0x01
    path.write_bytes(bytes(tampered))

    failed = await client.get(f"/api/v1/media/{media_id}/file")
    assert failed.status_code == 409
    assert "cannot be decrypted" in failed.json()["detail"]
    assert path.read_bytes() == bytes(tampered)  # never deleted or overwritten


async def test_thumbnail_of_encrypted_media_is_never_plaintext_on_disk(
    client: AsyncClient, db_session, encrypt_on, monkeypatch
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    media_id = r.json()["id"]
    # OCR and gallery paths share this decrypt-on-read behaviour.
    r = await client.get(f"/api/v1/media/{media_id}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert r.content[:4] == b"RIFF"  # decodable WebP, i.e. plaintext in transit

    media = (
        await db_session.execute(select(Media).where(Media.id == media_id))
    ).scalar_one()
    expected_cache = settings.MEDIA_DIR / "thumbs" / f"image-{Path(media.storage_path).name}.webp.llm1"
    thumbs = sorted((settings.MEDIA_DIR / "thumbs").glob(f"*{Path(media.storage_path).name}*"))
    assert thumbs, "encrypted cache must be written"
    for thumb in thumbs:
        on_disk = thumb.read_bytes()
        assert not on_disk.startswith(b"RIFF"), f"plaintext thumb leaked: {thumb.name}"
        assert media_crypto.is_encrypted(on_disk)
    assert thumbs[0] == expected_cache
    assert not (settings.MEDIA_DIR / "thumbs" / f"image-{Path(media.storage_path).name}.webp").exists()

    # Second request serves from the encrypted cache and still decrypts.
    again = await client.get(f"/api/v1/media/{media_id}/thumb")
    assert again.status_code == 200
    assert again.content == r.content


async def test_note_media_of_encrypted_note_is_encrypted_and_served_plaintext(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    note = Note(title="n", body="secret", is_deleted=False)
    note.is_encrypted = True
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)

    r = await client.post(
        f"/api/v1/notes/{note.id}/media",
        files={"file": ("snap.png", _png_bytes(), "image/png")},
    )
    assert r.status_code in (200, 201)
    media_id = r.json()["id"]
    stored = (
        await db_session.execute(select(NoteMedia).where(NoteMedia.note_id == note.id))
    ).scalar_one()
    blob = (settings.MEDIA_DIR / stored.storage_path).read_bytes()
    assert media_crypto.is_encrypted(blob)

    served = await client.get(f"/api/v1/notes/{note.id}/media/{media_id}/file")
    assert served.status_code == 200
    _assert_same_image(served.content, _png_bytes())

    assert stored.file_size == len(blob)


async def test_video_note_of_encrypted_entry_is_encrypted_and_served_plaintext(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    """Third attachment store: clips of encrypted entries obey the same rule."""
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/videos",
        data={"entry_id": str(entry.id)},
        files={"file": ("clip.mp4", b"fakemp4data" * 50, "video/mp4")},
    )
    assert r.status_code in (200, 201), r.text
    video_id = r.json()["id"]
    video = (
        await db_session.execute(
            select(VideoNote).where(VideoNote.id == video_id)
        )
    ).scalar_one()
    blob = (settings.MEDIA_DIR / video.storage_path).read_bytes()
    assert media_crypto.is_encrypted(blob)
    assert media_crypto.decrypt_media(blob, video.storage_path) == b"fakemp4data" * 50

    served = await client.get(f"/api/v1/videos/{video_id}/file")
    assert served.status_code == 200
    assert served.content == b"fakemp4data" * 50


async def test_delete_removes_the_encrypted_thumb_cache_too(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    entry = await _encrypted_entry(db_session, encrypted=True)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    media_id = r.json()["id"]
    await client.get(f"/api/v1/media/{media_id}/thumb")  # creates the .llm1 cache
    media = (
        await db_session.execute(select(Media).where(Media.id == media_id))
    ).scalar_one()
    thumb_prefix = f"image-{Path(media.storage_path).name}.webp"
    thumbs = (settings.MEDIA_DIR / "thumbs").glob(f"*{Path(media.storage_path).name}*")
    assert any(t.name.endswith(".llm1") for t in thumbs)

    await client.delete(f"/api/v1/media/{media_id}")
    leftovers = list(
        (settings.MEDIA_DIR / "thumbs").glob(f"*{Path(media.storage_path).name}*")
    )
    assert leftovers == [], f"thumb caches leaked: {leftovers}"
    assert thumb_prefix  # silence unused
