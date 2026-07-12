"""AES-256-GCM encryption service for journal entries."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.entry import Entry
from app.models.note import Note

# 12-byte nonce is standard for AES-GCM
_NONCE_SIZE = 12


class EncryptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes | None = None) -> bytes:
        """Derive a 256-bit key from a passphrase + salt via PBKDF2-HMAC-SHA256.

        ``salt`` should be a random per-entry salt (modern path). ``None`` falls
        back to the legacy deterministic (passphrase-derived) salt so entries
        encrypted before per-entry salts were introduced still decrypt.
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        if salt is None:
            # Legacy deterministic salt (pre-per-entry-salt entries).
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
        """Decrypt a base64-encoded nonce+ciphertext token.

        Raises ``ValueError`` on a wrong passphrase / corrupted token so callers
        can map it to a 400 rather than surfacing the crypto-internal
        ``InvalidTag`` as a 500.
        """
        from cryptography.exceptions import InvalidTag

        raw = base64.b64decode(token)
        nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        aesgcm = AESGCM(key)
        try:
            return aesgcm.decrypt(nonce, ct, None)
        except InvalidTag as exc:
            raise ValueError("Invalid passphrase or corrupted data") from exc

    async def encrypt_entry(self, entry_id: int, passphrase: str) -> Entry:
        """Encrypt the body and mood of an entry in-place. Title is kept readable."""
        entry = await self._get_entry(entry_id)

        if entry.is_encrypted:
            raise ValueError("Entry is already encrypted")

        salt = os.urandom(16)
        key = self._derive_key(passphrase, salt)
        entry.body = self._encrypt(entry.body.encode(), key)
        if entry.mood is not None:
            entry.mood = self._encrypt(entry.mood.encode(), key)
        entry.encryption_salt = base64.b64encode(salt).decode()

        entry.is_encrypted = True
        entry.encrypted_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def decrypt_entry(self, entry_id: int, passphrase: str) -> Entry:
        """Decrypt the body and mood of an entry in-place."""
        entry = await self._get_entry(entry_id)

        if not entry.is_encrypted:
            raise ValueError("Entry is not encrypted")

        salt = base64.b64decode(entry.encryption_salt) if entry.encryption_salt else None
        key = self._derive_key(passphrase, salt)

        entry.body = self._decrypt(entry.body, key).decode()
        if entry.mood is not None:
            entry.mood = self._decrypt(entry.mood, key).decode()
        entry.encryption_salt = None

        entry.is_encrypted = False
        entry.encrypted_at = None
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def get_encryption_status(self, entry_id: int) -> dict[str, object]:
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

    # ── Notes ──────────────────────────────────────────────────────────────

    async def encrypt_note(self, note_id: int, passphrase: str) -> Note:
        """Encrypt a note's body in-place. Title is kept readable (like entries)."""
        note = await self._get_note(note_id)
        if note.is_encrypted:
            raise ValueError("Note is already encrypted")
        salt = os.urandom(16)
        key = self._derive_key(passphrase, salt)
        note.body = self._encrypt(note.body.encode(), key)
        note.encryption_salt = base64.b64encode(salt).decode()
        note.is_encrypted = True
        note.encrypted_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def decrypt_note(self, note_id: int, passphrase: str) -> Note:
        """Decrypt a note's body in-place."""
        note = await self._get_note(note_id)
        if not note.is_encrypted:
            raise ValueError("Note is not encrypted")
        salt = base64.b64decode(note.encryption_salt) if note.encryption_salt else None
        key = self._derive_key(passphrase, salt)
        note.body = self._decrypt(note.body, key).decode()
        note.encryption_salt = None
        note.is_encrypted = False
        note.encrypted_at = None
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def get_note_encryption_status(self, note_id: int) -> dict[str, object]:
        """Return encryption status for a note."""
        note = await self._get_note(note_id)
        return {
            "note_id": note.id,
            "is_encrypted": note.is_encrypted,
            "encrypted_at": note.encrypted_at,
        }

    async def _get_note(self, note_id: int) -> Note:
        result = await self.db.execute(
            select(Note).where(Note.id == note_id, Note.is_deleted == False)  # noqa: E712
        )
        note = result.scalar_one_or_none()
        if not note:
            raise NotFoundError(f"Note {note_id} not found")
        return note
