"""Migration of existing media to encrypted-at-rest (SEC-MEDIA-5, design §7)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.services import media_crypto


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


async def _upload_to(client: AsyncClient, db_session, *, encrypted: bool) -> tuple[int, Media]:
    """Upload while the flag is off → legacy plaintext media, like a pre-0.14 store."""
    entry = Entry(entry_date=date(2026, 4, 1), body="x", title="t")
    entry.is_encrypted = encrypted
    db_session.add(entry)
    await db_session.commit()
    previous = settings.ENCRYPT_MEDIA
    settings.ENCRYPT_MEDIA = False  # upload plaintext
    try:
        r = await client.post(
            "/api/v1/media",
            data={"entry_id": str(entry.id)},
            files={"file": ("p.png", _png(), "image/png")},
        )
    finally:
        settings.ENCRYPT_MEDIA = previous
    assert r.status_code == 201
    media_id = r.json()["id"]
    media = (await db_session.execute(select_media(media_id))).scalar_one()
    return media_id, media


def select_media(media_id: int):
    from sqlalchemy import select

    return select(Media).where(Media.id == media_id)


@pytest.fixture
def encrypt_on(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPT_MEDIA", True)


async def test_migration_disabled_without_flag(client: AsyncClient) -> None:
    r = await client.post("/api/v1/settings/encrypt-media", params={"dry_run": "false"})
    assert r.status_code == 400
    assert "ENCRYPT_MEDIA" in r.json()["detail"]


async def test_dry_run_counts_without_writing(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    # Flag was off at upload time → legacy plaintext media on an encrypted parent.
    _media_id, media = await _upload_to(client, db_session, encrypted=True)
    path = settings.MEDIA_DIR / media.storage_path
    before = path.read_bytes()

    r = await client.post("/api/v1/settings/encrypt-media")
    assert r.status_code == 200
    report = r.json()
    assert report["dry_run"] is True
    assert report["candidates"] == 1
    assert report["plaintext_bytes"] == len(before)
    assert report["updated"] == 0
    assert path.read_bytes() == before  # untouched


async def test_apply_encrypts_and_is_idempotent(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    _media_id, media = await _upload_to(client, db_session, encrypted=True)
    path = settings.MEDIA_DIR / media.storage_path
    plaintext = path.read_bytes()

    r = await client.post("/api/v1/settings/encrypt-media", params={"dry_run": "false"})
    assert r.status_code == 200
    report = r.json()
    assert report["updated"] == 1
    assert report["errors"] == []

    blob = path.read_bytes()
    assert media_crypto.is_encrypted(blob)
    assert media_crypto.decrypt_media(blob, media.storage_path) == plaintext

    # Rerun is a no-op (resumable), and no thumb cache was involved.
    again = await client.post("/api/v1/settings/encrypt-media", params={"dry_run": "false"})
    assert again.json()["candidates"] == 0
    assert again.json()["updated"] == 0


async def test_apply_purges_plaintext_thumb_of_encrypted_media(
    client: AsyncClient, db_session, encrypt_on, monkeypatch
) -> None:
    media_id, media = await _upload_to(client, db_session, encrypted=True)

    # A plaintext thumb predating the encrypted cache (legacy state).
    thumb = settings.MEDIA_DIR / "thumbs" / f"image-{Path(media.storage_path).name}.webp"
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"RIFF-old-plaintext-webp")

    # Seed a plaintext thumb cache entry via the normal path (flag affects
    # uploads, not thumbs): fetch /thumb to generate it fresh and encrypted.
    # Simulate the legacy state by writing it BEFORE the migration instead —
    # the migration must delete it.
    r = await client.post("/api/v1/settings/encrypt-media", params={"dry_run": "false"})
    assert r.status_code == 200
    assert r.json()["thumbs_purged"] == 1
    assert not thumb.exists()


async def test_plaintext_items_never_touched(
    client: AsyncClient, db_session, encrypt_on
) -> None:
    _media_id, media = await _upload_to(client, db_session, encrypted=False)
    path = settings.MEDIA_DIR / media.storage_path
    before = path.read_bytes()
    r = await client.post("/api/v1/settings/encrypt-media", params={"dry_run": "false"})
    assert r.json()["candidates"] == 0
    assert r.json()["updated"] == 0
    assert path.read_bytes() == before
    assert not media_crypto.is_encrypted(path.read_bytes())
