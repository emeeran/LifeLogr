"""Integration tests for encryption — encrypt, decrypt, status."""

import base64

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.services.encryption_service import EncryptionService


async def _entry(client: AsyncClient):
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "Secret diary"}
    )
    return r.json()


class TestEncryption:
    async def test_encrypt_and_status(self, client: AsyncClient):
        e = await _entry(client)
        r = await client.post(
            f"/api/v1/entries/{e['id']}/encryption/encrypt", json={"passphrase": "mypass"}
        )
        assert r.status_code == 200
        assert r.json()["is_encrypted"] is True

        r = await client.get(f"/api/v1/entries/{e['id']}/encryption/status")
        assert r.json()["is_encrypted"] is True

    async def test_decrypt_roundtrip(self, client: AsyncClient):
        e = await _entry(client)
        await client.post(
            f"/api/v1/entries/{e['id']}/encryption/encrypt", json={"passphrase": "mypass"}
        )
        r = await client.post(
            f"/api/v1/entries/{e['id']}/encryption/decrypt", json={"passphrase": "mypass"}
        )
        assert r.status_code == 200
        assert r.json()["is_encrypted"] is False

    async def test_decrypt_wrong_passphrase_returns_400(self, client: AsyncClient):
        e = await _entry(client)
        await client.post(
            f"/api/v1/entries/{e['id']}/encryption/encrypt", json={"passphrase": "correct"}
        )
        r = await client.post(
            f"/api/v1/entries/{e['id']}/encryption/decrypt", json={"passphrase": "wrong"}
        )
        assert r.status_code == 400

    async def test_decrypt_note_wrong_passphrase_returns_400(self, client: AsyncClient):
        # Notes decrypt must also map a wrong passphrase to 400 (InvalidTag used
        # to propagate as a 500 — see AUDIT.md).
        n = await client.post(
            "/api/v1/notes/folders", json={"name": "nb"}
        )
        folder_id = n.json()["id"]
        note = await client.post(
            "/api/v1/notes", json={"title": "t", "body": "secret", "folder_id": folder_id}
        )
        nid = note.json()["id"]
        await client.post(
            f"/api/v1/notes/{nid}/encryption/encrypt", json={"passphrase": "correct"}
        )
        r = await client.post(
            f"/api/v1/notes/{nid}/encryption/decrypt", json={"passphrase": "wrong"}
        )
        assert r.status_code == 400

    async def test_encrypt_missing_entry_404(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/entries/9999/encryption/encrypt", json={"passphrase": "mypass"}
        )
        assert r.status_code == 404

    async def test_new_encryption_uses_random_per_entry_salt(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Two entries encrypted with the same passphrase must get distinct salts
        # (defeating precomputed/rainbow-table attacks across entries).
        e1 = await _entry(client)
        e2 = await _entry(client)
        await client.post(
            f"/api/v1/entries/{e1['id']}/encryption/encrypt", json={"passphrase": "same"}
        )
        await client.post(
            f"/api/v1/entries/{e2['id']}/encryption/encrypt", json={"passphrase": "same"}
        )
        rows = {
            r.id: r.encryption_salt
            for r in (
                await db_session.execute(select(Entry).where(Entry.id.in_([e1["id"], e2["id"]])))
            ).scalars()
        }
        assert rows[e1["id"]] and rows[e2["id"]]
        assert rows[e1["id"]] != rows[e2["id"]]
        assert len(base64.b64decode(rows[e1["id"]])) >= 16

    async def test_legacy_entry_without_salt_still_decrypts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # An entry encrypted before per-entry salts (deterministic salt, no
        # stored encryption_salt) must still decrypt via the fallback path.
        e = await _entry(client)
        svc = EncryptionService(db_session)
        entry = (
            await db_session.execute(select(Entry).where(Entry.id == e["id"]))
        ).scalar_one()
        legacy_key = svc._derive_key("legacypw", None)
        entry.body = svc._encrypt(b"Secret diary", legacy_key)
        entry.is_encrypted = True
        entry.encryption_salt = None
        await db_session.commit()

        r = await client.post(
            f"/api/v1/entries/{e['id']}/encryption/decrypt", json={"passphrase": "legacypw"}
        )
        assert r.status_code == 200
        assert r.json()["is_encrypted"] is False
