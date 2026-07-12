"""Integration tests for encryption — encrypt, decrypt, status."""

from httpx import AsyncClient


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
