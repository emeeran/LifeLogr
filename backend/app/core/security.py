"""AES-256-GCM encryption/decryption for cloud provider credentials.

v2 uses HKDF-SHA256 to derive a proper 256-bit key from SECRET_KEY.
Backward-compatible with v1 (null-padded key) for existing encrypted tokens.
"""

import base64
import json
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import settings

logger = logging.getLogger(__name__)

_V2_SALT = b"lifelogr-encryption-v2"
_V2_INFO = b"aes-256-gcm-key"

# v2 key: HKDF-derived from SECRET_KEY
_v2_key = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=_V2_SALT,
    info=_V2_INFO,
).derive(settings.SECRET_KEY.encode())

# v1 key: legacy null-padded key (for backward compat)
_v1_key = settings.SECRET_KEY.encode().ljust(32, b"\0")[:32]

_VERSION_PREFIX = b"\x02"


def token_version(token: str) -> int:
    """Return the encryption format version of a stored token (1 or 2).

    Useful for monitoring/migration: tokens that report v1 should be re-encrypted
    via :func:`reencrypt` at the next write opportunity.
    """
    try:
        raw = base64.b64decode(token)
    except Exception:
        return 1  # treat undecodable as legacy
    return 2 if raw[:1] == _VERSION_PREFIX else 1


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


def reencrypt(token: str) -> str:
    """Upgrade a legacy v1 token to the v2 HKDF format; v2 tokens pass through.

    Call this whenever a credential is read-then-written back (e.g. on OAuth
    token refresh) so the v1 fallback path can eventually be retired.
    """
    if token_version(token) == 2:
        return token
    return encrypt(decrypt(token))


def load_stored_credentials(
    credentials_encrypted: str | None,
    fallback_client_id: str | None,
    fallback_client_secret: str | None,
    *,
    provider: str,
) -> tuple[str | None, str | None, dict[str, str]]:
    """Decrypt a backup provider's stored OAuth credentials, with fallback.

    Used by the Box/Dropbox/OneDrive/Google-Drive callback + auth-url routes,
    which all need the same "decrypt the stored ``BackupConfig`` blob, fall
    back to the configured defaults, tolerate a corrupt/legacy blob" logic.

    Returns ``(client_id, client_secret, stored)`` where ``stored`` is the full
    decrypted dict on success (empty on failure/no-config) so callers can read
    other keys such as ``refresh_token``. Stored values override the fallbacks
    when present and non-empty; a decrypt/parse failure logs a warning and
    returns the fallbacks, so re-connecting works even if the old blob is
    unreadable.
    """
    if not credentials_encrypted:
        return fallback_client_id, fallback_client_secret, {}
    try:
        stored = json.loads(decrypt(credentials_encrypted))
    except Exception:
        logger.warning("Failed to decrypt stored %s credentials", provider, exc_info=True)
        return fallback_client_id, fallback_client_secret, {}
    return (
        stored.get("client_id") or fallback_client_id,
        stored.get("client_secret") or fallback_client_secret,
        stored,
    )
