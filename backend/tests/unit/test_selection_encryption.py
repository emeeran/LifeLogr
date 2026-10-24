"""Tests for selection (/encryption/encrypt-text) encryption.

Locks in the salted scrypt envelope: the endpoint used to derive its key from
the passphrase alone, which made every offline dictionary attack a local
computation. Also covers the hard refusal to encrypt while the app runs on the
public default SECRET_KEY.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import DEFAULT_SECRET_KEY
from app.services.encryption_service import EncryptionService

_ENCRYPT = "/api/v1/encryption/encrypt-text"
_DECRYPT = "/api/v1/encryption/decrypt-text"


class TestDefaultKeyRefusal:
    async def test_encrypt_text_rejects_default_secret_key(self, client: AsyncClient) -> None:
        assert settings.SECRET_KEY == DEFAULT_SECRET_KEY  # the shipped default
        r = await client.post(_ENCRYPT, json={"text": "dear diary", "passphrase": "pw"})
        assert r.status_code == 403
        assert "SECRET_KEY" in r.json()["detail"]

    async def test_encrypt_still_rejected_when_test_env_allowed(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The selection surface is strict — no test-env allowance, unlike credentials."""
        monkeypatch.setattr(settings, "SECRET_KEY", "change-me-before-production")
        r = await client.post(_ENCRYPT, json={"text": "dear diary", "passphrase": "pw"})
        assert r.status_code == 403

    async def test_credential_encrypt_hard_fails_outside_test_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """security.encrypt() refuses the public key on any real (non-test) run."""
        from app.core import security

        monkeypatch.setattr(settings, "APP_ENV", "development")
        with pytest.raises(security.DefaultSecretKeyError, match="SECRET_KEY"):
            security.encrypt("cloud-oauth-refresh-token")

    async def test_credential_encrypt_allowed_with_custom_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import security

        monkeypatch.setattr(settings, "APP_ENV", "development")
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")
        assert security.decrypt(security.encrypt("secret")) == "secret"


class TestSaltedV2Envelope:
    async def test_roundtrip_and_salt_presence(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")
        r = await client.post(_ENCRYPT, json={"text": "secret thought", "passphrase": "pw"})
        assert r.status_code == 200
        envelope = r.json()["encrypted"]
        # Self-describing versioned envelope: v2:<salt>:<nonce+ciphertext>
        assert envelope.startswith("v2:")
        salt_b64, token = envelope[3:].split(":", 1)
        salt = base64.b64decode(salt_b64)
        assert len(salt) >= 16, "a per-item random salt must travel with the ciphertext"

        d = await client.post(_DECRYPT, json={"encrypted_text": envelope, "passphrase": "pw"})
        assert d.status_code == 200
        assert d.json()["decrypted"] == "secret thought"

    async def test_two_encryptions_use_different_salts(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")
        e1 = (
            await client.post(_ENCRYPT, json={"text": "same", "passphrase": "pw"})
        ).json()["encrypted"]
        e2 = (
            await client.post(_ENCRYPT, json={"text": "same", "passphrase": "pw"})
        ).json()["encrypted"]
        assert e1 != e2, "same text + passphrase must not be ciphertext-identical"
        assert e1[3:].split(":", 1)[0] != e2[3:].split(":", 1)[0]

    async def test_challenge_is_the_sha256_of_a_random_verifier(self) -> None:
        """PKCE-style sanity on the primitives the envelope relies on."""
        from app.core.oauth_state import code_challenge_s256, generate_code_verifier

        verifier = generate_code_verifier()
        assert 43 <= len(verifier) <= 128
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        assert code_challenge_s256(verifier) == expected.decode().rstrip("=")

    async def test_wrong_passphrase_fails(self, client: AsyncClient, monkeypatch) -> None:
        monkeypatch.setattr(settings, "SECRET_KEY", "a-real-key")
        envelope = (
            await client.post(_ENCRYPT, json={"text": "secret", "passphrase": "right"})
        ).json()["encrypted"]
        r = await client.post(_DECRYPT, json={"encrypted_text": envelope, "passphrase": "wrong"})
        assert r.status_code == 400


class TestLegacyCompat:
    async def test_old_deterministic_salt_envelope_still_decrypts(
        self, client: AsyncClient
    ) -> None:
        """Selections encrypted before the salted KDF must remain readable."""
        svc = EncryptionService(None)  # type: ignore[arg-type]
        legacy_token = svc._encrypt(b"old selection", svc._derive_key("pw"))
        r = await client.post(_DECRYPT, json={"encrypted_text": legacy_token, "passphrase": "pw"})
        assert r.status_code == 200
        assert r.json()["decrypted"] == "old selection"

    async def test_service_encrypt_free_text_matches_entry_kdf(self) -> None:
        """The envelope reuses the same scrypt parameters as entry encryption."""
        svc = EncryptionService(None)  # type: ignore[arg-type]
        envelope = await svc.encrypt_free_text("hello", "pw")
        salt_b64, token = envelope[len("v2:") :].split(":", 1)
        salt = base64.b64decode(salt_b64)
        key = svc._derive_key_scrypt("pw", salt)
        assert svc._decrypt(token, key) == b"hello"
