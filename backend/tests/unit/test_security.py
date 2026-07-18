"""Integration tests for security — encrypt/decrypt roundtrip."""

from app.core.security import decrypt, encrypt


class TestEncryptDecrypt:
    def test_roundtrip(self):
        plaintext = "Hello secret world"
        token = encrypt(plaintext)
        assert decrypt(token) == plaintext

    def test_different_tokens_each_time(self):
        text = "same input"
        t1 = encrypt(text)
        t2 = encrypt(text)
        assert t1 != t2  # nonce-based


class TestTokenVersionAndReencrypt:
    """v1/v2 token format detection and migration."""

    def test_encrypt_produces_v2_token(self):
        from app.core.security import token_version

        assert token_version(encrypt("anything")) == 2

    def test_reencrypt_passes_through_v2(self):
        from app.core.security import reencrypt

        v2 = encrypt("v2 payload")
        assert reencrypt(v2) == v2  # unchanged

    def test_reencrypt_upgrades_v1_to_v2(self):
        """A hand-crafted v1 token must decrypt correctly and upgrade to v2."""
        import base64

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from app.core import security

        nonce = b"\x00" * 12
        plaintext = "legacy secret"
        # Build a v1 token: raw nonce + ciphertext under the null-padded v1 key.
        ct = AESGCM(security._v1_key).encrypt(nonce, plaintext.encode(), None)
        v1_token = base64.b64encode(nonce + ct).decode()

        assert security.token_version(v1_token) == 1
        assert security.decrypt(v1_token) == plaintext  # still readable

        upgraded = security.reencrypt(v1_token)
        assert security.token_version(upgraded) == 2
        assert security.decrypt(upgraded) == plaintext  # content preserved


class TestLoadStoredCredentials:
    """Shared credential loading for the Box/Dropbox/OneDrive/Google routers."""

    def test_no_stored_returns_fallbacks(self):
        from app.core.security import load_stored_credentials

        cid, secret, stored = load_stored_credentials(
            None, "default-id", "default-secret", provider="dropbox"
        )
        assert cid == "default-id"
        assert secret == "default-secret"
        assert stored == {}

    def test_stored_overrides_fallbacks(self):
        import json

        from app.core.security import encrypt, load_stored_credentials

        blob = encrypt(
            json.dumps(
                {"client_id": "stored-id", "client_secret": "stored-secret", "refresh_token": "rt"}
            )
        )
        cid, secret, stored = load_stored_credentials(
            blob, "default-id", "default-secret", provider="dropbox"
        )
        assert cid == "stored-id"
        assert secret == "stored-secret"
        assert stored["refresh_token"] == "rt"

    def test_partial_stored_keeps_fallback(self):
        import json

        from app.core.security import encrypt, load_stored_credentials

        blob = encrypt(json.dumps({"client_id": "stored-id"}))  # no client_secret
        cid, secret, _ = load_stored_credentials(
            blob, "default-id", "default-secret", provider="box"
        )
        assert cid == "stored-id"
        assert secret == "default-secret"  # fallback retained

    def test_corrupt_blob_returns_fallbacks(self):
        from app.core.security import load_stored_credentials

        cid, secret, stored = load_stored_credentials(
            "not-a-valid-encrypted-blob", "default-id", "default-secret", provider="onedrive"
        )
        assert cid == "default-id"
        assert secret == "default-secret"
        assert stored == {}

    def test_empty_stored_value_falls_back(self):
        import json

        from app.core.security import encrypt, load_stored_credentials

        blob = encrypt(json.dumps({"client_id": "", "client_secret": ""}))
        cid, secret, _ = load_stored_credentials(
            blob, "default-id", "default-secret", provider="google"
        )
        assert cid == "default-id"  # empty stored value → fallback (truthiness semantics)
        assert secret == "default-secret"
