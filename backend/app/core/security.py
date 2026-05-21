"""AES-256-GCM encryption/decryption for cloud provider credentials."""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_KEY = settings.SECRET_KEY.encode().ljust(32, b"\0")[:32]


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded nonce+ciphertext."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(_KEY).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded nonce+ciphertext back to plaintext."""
    raw = base64.b64decode(token)
    return AESGCM(_KEY).decrypt(raw[:12], raw[12:], None).decode()
