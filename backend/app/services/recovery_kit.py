"""Recovery kit: wrap ``SECRET_KEY`` in a passphrase-protected file (SEC-KEYS).

Losing ``SECRET_KEY`` loses every stored cloud credential **and** (since media
encryption) every encrypted attachment. The recovery kit is a small JSON file
(``lifelogr-recovery.json``) holding the current key wrapped with a
passphrase:

    scrypt(passphrase, salt, n=2^15, r=8, p=1) → 32-byte KEK
    AES-256-GCM(KEK, nonce, SECRET_KEY, aad="lifelogr-recovery-kit-v1")

The passphrase may be user-chosen **or** the generated 24-character recovery
code (120 bits of base32, grouped ``XXXX-…``) — the code *is* the KDF input,
so import needs no special code path.

Import verifies the candidate key against the installation before persisting:
it probe-decrypts one stored credential and one encrypted media chunk and
refuses a key that cannot read them (design §8). Persisting only happens on
managed runs (``DATA_DIR/.secret_key``) — a dev/server run sources its key
from the environment, which no file can override.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_SECRET_KEY, _is_managed_run, settings
from app.core.security import is_default_secret_key
from app.models.backup import BackupConfig
from app.services import media_crypto

logger = logging.getLogger(__name__)

KIT_FORMAT = 1
_KIT_AAD = b"lifelogr-recovery-kit-v1"
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_SIZE = 16

_CODE_CHARS = 24  # 24 × 5 bits = 120 bits
_CODE_GROUP = 4


class RecoveryKitError(Exception):
    """Raised for a wrong passphrase/code or a kit that doesn't fit this install."""


def generate_recovery_code() -> str:
    """24 base32 characters, grouped ``XXXX-XXXX-…`` (dashes are cosmetic)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    raw = "".join(secrets.choice(alphabet) for _ in range(_CODE_CHARS))
    return "-".join(raw[i : i + _CODE_GROUP] for i in range(0, len(raw), _CODE_GROUP))


def _kit_secret(passphrase: str) -> str:
    """Normalise a passphrase/recovery code for the KDF."""
    return passphrase.strip().upper().replace("-", "").replace(" ", "")


def _derive_kek(secret: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(
        secret.encode()
    )


def export_kit(passphrase: str | None = None) -> dict[str, Any]:
    """Build the recovery-kit document for the current ``SECRET_KEY``.

    With *passphrase* the kit is wrapped with it; without, a recovery code is
    generated and returned in ``code`` — it is the only way to open the file.
    Returns ``{"kit": <json-ready dict>, "code": str | None}``.
    """
    if is_default_secret_key() and settings.APP_ENV.strip().lower() not in ("test", "testing"):
        raise RecoveryKitError(
            "This installation still uses the public default key — nothing to "
            "protect. Set a SECRET_KEY (the packaged app does this "
            "automatically) before exporting a recovery kit."
        )

    code: str | None = None
    secret = passphrase.strip() if passphrase and passphrase.strip() else None
    if secret is None:
        code = generate_recovery_code()
        secret = _kit_secret(code)  # codes unwrap via the normalised form

    salt = os.urandom(_SALT_SIZE)
    kek = _derive_kek(secret, salt)
    nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce, settings.SECRET_KEY.encode(), _KIT_AAD)

    kit = {
        "format": KIT_FORMAT,
        "kdf": {
            "name": "scrypt",
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
            "salt": base64.b64encode(salt).decode(),
        },
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(wrapped).decode(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": settings.APP_VERSION,
    }
    # Record the export so the settings UI can warn encrypted installs that
    # have never made a kit (the flag survives restarts via runtime settings).
    settings.RECOVERY_KIT_EXPORTED_AT = str(kit["created_at"])
    from app.services.settings_service import persist_runtime_settings

    persist_runtime_settings()
    return {"kit": kit, "code": code}


def _unwrap(kit: dict[str, Any], passphrase: str) -> str:
    """Decrypt the kit's wrapped SECRET_KEY (raises RecoveryKitError on failure)."""
    try:
        if kit.get("format") != KIT_FORMAT:
            raise ValueError("unsupported kit format")
        kdf = kit["kdf"]
        if kdf.get("name") != "scrypt":
            raise ValueError("unsupported kdf")
        salt = base64.b64decode(kdf["salt"])
        nonce = base64.b64decode(kit["nonce"])
        wrapped = base64.b64decode(kit["ciphertext"])
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
        if not (2**14 <= n <= 2**17 and r in (8,) and p == 1):
            raise ValueError("kdf parameters outside the accepted range")
    except (KeyError, ValueError, TypeError) as exc:
        raise RecoveryKitError(f"Not a valid LifeLogr recovery kit: {exc}") from exc

    # Try the input literally first (human passphrases keep their case and
    # spaces), then the normalised form (recovery codes: case-insensitive,
    # dashes/spaces ignored). Both fail → wrong secret.
    last_exc: InvalidTag | None = None
    for attempt in (passphrase.strip(), _kit_secret(passphrase)):
        kek = _derive_kek(attempt, salt)
        try:
            return AESGCM(kek).decrypt(nonce, wrapped, _KIT_AAD).decode()
        except InvalidTag as exc:
            last_exc = exc
    raise RecoveryKitError(
        "Wrong passphrase or recovery code (or the kit file is damaged)"
    ) from last_exc


async def _probe_credentials(db: AsyncSession, candidate: str) -> str:
    """``ok`` / ``failed`` / ``skipped`` against one stored credential token."""
    row = (await db.execute(select(BackupConfig.credentials_encrypted).limit(1))).first()
    if row is None:
        return "skipped"
    token = row[0]
    raw = base64.b64decode(token)
    if raw[:1] == b"\x02":
        key = _credentials_key(candidate)
        try:
            AESGCM(key).decrypt(raw[1:13], raw[13:], None)
            return "ok"
        except InvalidTag:
            return "failed"
    return "skipped"  # v1 legacy token: null-padded-key format, skip


def _credentials_key(secret: str) -> bytes:
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"lifelogr-encryption-v2",
        info=b"aes-256-gcm-key",
    ).derive(secret.encode())


async def _probe_media(db: AsyncSession, candidate: str) -> str:
    """``ok`` / ``failed`` / ``skipped`` against one encrypted media blob."""
    from app.models.media import Media
    from app.models.note_media import NoteMedia

    # No LIMIT: a sampled probe that happens to miss every encrypted blob
    # would report "skipped" and let a wrong key be installed — the one
    # failure mode the probe exists to prevent. The scan is cheap (28-byte
    # header read per file) and stops at the first encrypted blob.
    for model in (Media, NoteMedia):
        rows = (await db.execute(select(model.storage_path))).all()
        for (storage_path,) in rows:
            path = settings.MEDIA_DIR / storage_path
            if not path.is_file():
                continue
            encrypted, _plain_len = media_crypto.probe_file(path)
            if not encrypted:
                continue
            media_key = media_crypto.derive_media_key(candidate)
            try:
                media_crypto.read_range_file(path, storage_path, 0, 1, key=media_key)
                return "ok"
            except ValueError:
                return "failed"
    return "skipped"


async def import_kit(
    db: AsyncSession,
    kit: dict[str, Any],
    passphrase: str,
    *,
    confirm_replace: bool = False,
) -> dict[str, Any]:
    """Unwrap, probe against this installation's data, then persist the key.

    Returns a report with the probe outcomes. Raises :class:`RecoveryKitError`
    for a bad passphrase/damaged kit or a key that cannot read the existing
    data, and a ConflictError-shaped dict refusal when a different non-default
    key is already active without ``confirm_replace``.
    """
    candidate = _unwrap(kit, passphrase)

    if not candidate or len(candidate) < 16:
        raise RecoveryKitError("Recovered key looks invalid — refusing to install it")

    cred_probe = await _probe_credentials(db, candidate)
    media_probe = await _probe_media(db, candidate)
    if "failed" in (cred_probe, media_probe):
        raise RecoveryKitError(
            "This kit's key cannot read this installation's data — it belongs "
            "to a different LifeLogr installation"
        )

    if settings.SECRET_KEY == candidate:
        return {
            "status": "unchanged",
            "probes": {"credentials": cred_probe, "media": media_probe},
        }
    if settings.SECRET_KEY != DEFAULT_SECRET_KEY and not confirm_replace:
        return {
            "status": "confirm_replace",
            "probes": {"credentials": cred_probe, "media": media_probe},
        }

    _persist_secret_key(candidate)
    return {
        "status": "restored",
        "probes": {"credentials": cred_probe, "media": media_probe},
    }


def _persist_secret_key(candidate: str) -> None:
    """Install *candidate* as the running SECRET_KEY (managed runs only).

    Writes ``DATA_DIR/.secret_key`` (mode 0600), updates the in-process
    settings and re-derives every cached key so no restart is needed. Refused
    for unmanaged runs, where the key comes from env/.env and a file would be
    silently ignored on the next start.
    """
    from app.core import security

    if not _is_managed_run():
        raise RecoveryKitError(
            "This installation sources its SECRET_KEY from the environment — "
            "a recovery kit cannot replace it. Update SECRET_KEY in .env and "
            "restart instead."
        )

    key_file = Path(settings.DATA_DIR) / ".secret_key"
    prev = os.umask(0o077)
    try:
        key_file.write_text(candidate)
    except OSError as exc:
        raise RecoveryKitError(f"Could not write {key_file}: {exc}") from exc
    finally:
        os.umask(prev)

    settings.SECRET_KEY = candidate
    security.rekey(candidate)
    media_crypto._cached_media_key.cache_clear()
    logger.warning("SECRET_KEY restored from a recovery kit — rotating caches")
