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
