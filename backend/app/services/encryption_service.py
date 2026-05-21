"""AES-256-GCM encryption service for journal entries."""
from __future__ import annotations

import base64
import os
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.entry import Entry

# 12-byte nonce is standard for AES-GCM
_NONCE_SIZE = 12


class EncryptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _derive_key(passphrase: str) -> bytes:
        """Derive a 256-bit key from a passphrase using PBKDF2-HMAC-SHA256."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        # Use a fixed salt derived from the passphrase itself so the same
        # passphrase always produces the same key (acceptable for local-only app).
        salt = passphrase.encode().ljust(32, b"\x00")[:32]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,
        )
        return kdf.derive(passphrase.encode())

    @staticmethod
    def _encrypt(plaintext: bytes, key: bytes) -> str:
        """Encrypt plaintext with AES-256-GCM; return base64-encoded nonce+ciphertext."""
        nonce = os.urandom(_NONCE_SIZE)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return base64.b64encode(nonce + ct).decode()

    @staticmethod
    def _decrypt(token: str, key: bytes) -> bytes:
        """Decrypt a base64-encoded nonce+ciphertext token."""
        raw = base64.b64decode(token)
        nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None)

    async def encrypt_entry(self, entry_id: int, passphrase: str) -> Entry:
        """Encrypt the body and mood of an entry in-place. Title is kept readable."""
        entry = await self._get_entry(entry_id)

        if entry.is_encrypted:
            raise ValueError("Entry is already encrypted")

        key = self._derive_key(passphrase)
        entry.body = self._encrypt(entry.body.encode(), key)
        if entry.mood is not None:
            entry.mood = self._encrypt(entry.mood.encode(), key)

        entry.is_encrypted = True
        entry.encrypted_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def decrypt_entry(self, entry_id: int, passphrase: str) -> Entry:
        """Decrypt the body and mood of an entry in-place."""
        entry = await self._get_entry(entry_id)

        if not entry.is_encrypted:
            raise ValueError("Entry is not encrypted")

        key = self._derive_key(passphrase)

        entry.body = self._decrypt(entry.body, key).decode()
        if entry.mood is not None:
            entry.mood = self._decrypt(entry.mood, key).decode()

        entry.is_encrypted = False
        entry.encrypted_at = None
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def get_encryption_status(self, entry_id: int) -> dict:
        """Return encryption status for an entry."""
        entry = await self._get_entry(entry_id)
        return {
            "entry_id": entry.id,
            "is_encrypted": entry.is_encrypted,
            "encrypted_at": entry.encrypted_at,
        }

    async def _get_entry(self, entry_id: int) -> Entry:
        result = await self.db.execute(
            select(Entry).where(Entry.id == entry_id, Entry.is_deleted == False)  # noqa: E712
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found")
        return entry
