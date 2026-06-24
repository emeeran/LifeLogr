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
