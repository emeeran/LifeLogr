"""Recovery kit round-trip (SEC-KEYS, design note §8 + §12).

Export → wipe → import → decrypt, plus the refusal paths: wrong passphrase,
wrong code, damaged kit, key that belongs to another installation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core import security
from app.services import media_crypto, recovery_kit


@pytest.fixture
def managed_run(monkeypatch, tmp_path):
    """A managed run with its own .secret_key, like the desktop app."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "SECRET_KEY", "installed-key-0123456789abcdef")
    security.rekey(settings.SECRET_KEY)
    media_crypto._cached_media_key.cache_clear()
    yield tmp_path
    security.rekey("installed-key-0123456789abcdef")
    media_crypto._cached_media_key.cache_clear()


async def _seed_credential(db_session) -> None:
    from app.models.backup import BackupConfig

    db_session.add(BackupConfig(provider="gdrive", credentials_encrypted=security.encrypt('{"t":1}')))
    await db_session.commit()


async def test_export_and_code_roundtrip(client: AsyncClient, db_session, managed_run) -> None:
    await _seed_credential(db_session)

    r = await client.post("/api/v1/settings/recovery-kit/export", json={})
    assert r.status_code == 200
    body = r.json()
    kit, code = body["kit"], body["code"]
    assert code and len(code.replace("-", "")) == 24
    assert kit["format"] == 1
    assert kit["kdf"]["name"] == "scrypt"
    assert "SECRET" not in r.text  # the raw key is never returned

    # Wipe the key, then restore from the kit with the code.
    settings.SECRET_KEY = "a-freshly-generated-unrelated-key"
    security.rekey(settings.SECRET_KEY)
    media_crypto._cached_media_key.cache_clear()

    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={
            "kit": kit,
            "passphrase": code.lower(),  # code is case-insensitive
            # A wiped install auto-generates a new non-default key, so the
            # restore must confirm it is replacing a live key.
            "confirm_replace": True,
        },
    )
    assert r.status_code == 200
    report = r.json()
    assert report["status"] == "restored"
    assert report["probes"]["credentials"] == "ok"
    assert settings.SECRET_KEY == "installed-key-0123456789abcdef"
    assert (Path(managed_run) / ".secret_key").read_text() == "installed-key-0123456789abcdef"

    # Credentials are readable again in-process.
    assert security.decrypt(security.encrypt("roundtrip")) == "roundtrip"


async def test_passphrase_kit_roundtrip(client: AsyncClient, db_session, managed_run) -> None:
    await _seed_credential(db_session)
    r = await client.post(
        "/api/v1/settings/recovery-kit/export", json={"passphrase": "correct horse"}
    )
    assert r.status_code == 200
    assert r.json()["code"] is None
    kit = r.json()["kit"]

    settings.SECRET_KEY = "another-unrelated-key-0123456789"
    security.rekey(settings.SECRET_KEY)
    media_crypto._cached_media_key.cache_clear()

    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": "correct horse", "confirm_replace": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "restored"
    assert settings.SECRET_KEY == "installed-key-0123456789abcdef"


async def test_media_probe_fails_for_foreign_key(client: AsyncClient, db_session, managed_run) -> None:
    # An encrypted blob on disk, so the probe has something to check.
    rel = "images/probe-target.webp"
    blob = settings.MEDIA_DIR / rel
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(media_crypto.encrypt_media(b"secretbytes" * 10, rel))
    from app.models.media import Media

    from datetime import date

    from app.models.entry import Entry

    entry = Entry(entry_date=date(2026, 5, 1), body="b", title="t")
    db_session.add(entry)
    await db_session.commit()
    db_session.add(Media(entry_id=entry.id, filename="x.webp", media_type="image",
                         file_size=blob.stat().st_size, storage_path=rel))
    await db_session.commit()

    r = await client.post("/api/v1/settings/recovery-kit/export", json={})
    kit, code = r.json()["kit"], r.json()["code"]

    # A kit from a DIFFERENT installation (different wrapped key).
    monkeypatched = "not-the-installed-key-at-all-12345"
    old = settings.SECRET_KEY
    settings.SECRET_KEY = monkeypatched
    foreign = recovery_kit.export_kit(None)
    settings.SECRET_KEY = old

    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": foreign["kit"], "passphrase": foreign["code"]},
    )
    assert r.status_code == 400
    assert "different LifeLogr installation" in r.json()["detail"]
    # The first kit still works — the file was never touched.
    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": code},
    )
    assert r.status_code == 200
    assert r.json()["probes"]["media"] == "ok"


async def test_wrong_passphrase_refused(client: AsyncClient, managed_run) -> None:
    r = await client.post(
        "/api/v1/settings/recovery-kit/export", json={"passphrase": "right"}
    )
    kit = r.json()["kit"]
    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": "wrong"},
    )
    assert r.status_code == 400
    assert "Wrong passphrase" in r.json()["detail"]
    assert settings.SECRET_KEY == "installed-key-0123456789abcdef"


async def test_damaged_kit_refused(client: AsyncClient, managed_run) -> None:
    r = await client.post("/api/v1/settings/recovery-kit/export", json={})
    kit = r.json()["kit"]
    kit["kdf"]["n"] = 2**30  # out of accepted range
    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": r.json()["code"]},
    )
    assert r.status_code == 400
    assert "valid LifeLogr recovery kit" in r.json()["detail"]


async def test_replace_requires_confirmation(client: AsyncClient, managed_run) -> None:
    r = await client.post("/api/v1/settings/recovery-kit/export", json={})
    kit, code = r.json()["kit"], r.json()["code"]

    # A different non-default key is active: import must ask first.
    settings.SECRET_KEY = "a-different-active-key-0123456789"
    security.rekey(settings.SECRET_KEY)
    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": code},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "confirm_replace"

    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": code, "confirm_replace": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "restored"
    assert settings.SECRET_KEY == "installed-key-0123456789abcdef"


async def test_unmanaged_run_refuses_import(client: AsyncClient, monkeypatch, managed_run) -> None:
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("LIFELOGR_DATA_DIR", raising=False)
    r = await client.post("/api/v1/settings/recovery-kit/export", json={})
    kit, code = r.json()["kit"], r.json()["code"]
    settings.SECRET_KEY = "a-different-active-key-0123456789"
    security.rekey(settings.SECRET_KEY)
    r = await client.post(
        "/api/v1/settings/recovery-kit/import",
        json={"kit": kit, "passphrase": code, "confirm_replace": True},
    )
    assert r.status_code == 400
    assert "environment" in r.json()["detail"]
