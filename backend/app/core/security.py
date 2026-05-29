"""AES-256-GCM encryption/decryption for cloud provider credentials.

v2 uses HKDF-SHA256 to derive a proper 256-bit key from SECRET_KEY.
Backward-compatible with v1 (null-padded key) for existing encrypted tokens.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import settings

_V2_SALT = b"diarilinux-encryption-v2"
_V2_INFO = b"aes-256-gcm-key"

# v2 key: HKDF-derived from SECRET_KEY
_v2_key = (
    HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_V2_SALT,
        info=_V2_INFO,
    )
    .derive(settings.SECRET_KEY.encode())
)

# v1 key: legacy null-padded key (for backward compat)
_v1_key = settings.SECRET_KEY.encode().ljust(32, b"\0")[:32]

_VERSION_PREFIX = b"\x02"


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded version prefix + nonce + ciphertext."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(_v2_key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(_VERSION_PREFIX + nonce + ciphertext).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded token, supporting both v1 and v2 formats."""
    raw = base64.b64decode(token)

    # v2 format: starts with \x02 prefix byte
    if raw[:1] == _VERSION_PREFIX:
        return AESGCM(_v2_key).decrypt(raw[1:13], raw[13:], None).decode()

    # v1 legacy format: raw nonce + ciphertext with null-padded key
    return AESGCM(_v1_key).decrypt(raw[:12], raw[12:], None).decode()
