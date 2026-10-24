"""AES-256-GCM encryption service for journal entries."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.embedding import NoteEmbedding
from app.models.entry import Entry
from app.models.note import Note

logger = logging.getLogger(__name__)

# 12-byte nonce is standard for AES-GCM
_NONCE_SIZE = 12

# Per-item KDF salt size (16 random bytes → 112 bits of entropy, ample for a
# memory-hard KDF whose work factor dominates any offline attack).
_SALT_SIZE = 16

# KDF versioning for passphrase-derived keys. The stored ``encryption_salt``
# carries a prefix so decrypt knows which KDF encrypted the entry — an entry can
# never become undecryptable, so every historical KDF stays supported:
#   "v2:<b64>" → scrypt (memory-hard; current default for new encryptions)
#   "<b64>"    → legacy PBKDF2-HMAC-SHA256 with a per-entry salt
#   None       → oldest legacy PBKDF2 with the deterministic (passphrase-derived) salt
_KDF_V2_PREFIX = "v2:"
# scrypt cost (N=2^15, r=8, p=1) → ~32 MiB memory, ~0.1–0.3s — memory-hard, so
# far more GPU/ASIC-resistant than PBKDF2 at any practical iteration count.
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1


class EncryptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes | None = None) -> bytes:
        """Derive a 256-bit key via PBKDF2-HMAC-SHA256 (the *legacy* KDF).

        Retained so entries encrypted before scrypt became the default still
        decrypt. ``salt=None`` falls back to the deterministic (passphrase-derived)
        salt for the oldest entries.
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
    def _derive_key_scrypt(passphrase: str, salt: bytes) -> bytes:
        """Derive a 256-bit key with scrypt (memory-hard; the current default)."""
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

        kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return kdf.derive(passphrase.encode())

    @staticmethod
    def _derive_key_for_decrypt(passphrase: str, stored_salt: str | None) -> bytes:
        """Pick the KDF from the stored-salt format and derive the key.

        See the ``_KDF_V2_PREFIX`` note above for the three supported formats.
        """
        if stored_salt and stored_salt.startswith(_KDF_V2_PREFIX):
            salt = base64.b64decode(stored_salt[len(_KDF_V2_PREFIX) :])
            return EncryptionService._derive_key_scrypt(passphrase, salt)
        return EncryptionService._derive_key(
            passphrase, base64.b64decode(stored_salt) if stored_salt else None
        )

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

        salt = os.urandom(_SALT_SIZE)
        # scrypt/PBKDF2 are deliberately slow (0.1–0.5s); run them plus the AES
        # work in a worker thread so the event loop keeps serving other requests.
        key = await asyncio.to_thread(self._derive_key_scrypt, passphrase, salt)
        entry.body = await asyncio.to_thread(self._encrypt, entry.body.encode(), key)
        if entry.mood is not None:
            entry.mood = await asyncio.to_thread(self._encrypt, entry.mood.encode(), key)
        entry.encryption_salt = _KDF_V2_PREFIX + base64.b64encode(salt).decode()

        entry.is_encrypted = True
        entry.encrypted_at = datetime.now(timezone.utc)
        # Encrypted content must not stay similarity-searchable: the semantic
        # index would otherwise hold a plaintext-derived vector of exactly the
        # text that was just hidden (and could be inverted via a search oracle).
        await self._delete_entry_embeddings(entry.id)
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def decrypt_entry(self, entry_id: int, passphrase: str) -> Entry:
        """Decrypt the body and mood of an entry in-place."""
        entry = await self._get_entry(entry_id)

        if not entry.is_encrypted:
            raise ValueError("Entry is not encrypted")

        key = await asyncio.to_thread(
            self._derive_key_for_decrypt, passphrase, entry.encryption_salt
        )

        entry.body = (await asyncio.to_thread(self._decrypt, entry.body, key)).decode()
        if entry.mood is not None:
            entry.mood = (await asyncio.to_thread(self._decrypt, entry.mood, key)).decode()
        entry.encryption_salt = None

        entry.is_encrypted = False
        entry.encrypted_at = None
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def _delete_entry_embeddings(self, entry_id: int) -> None:
        """Drop the entry's semantic-embedding row, if one exists."""
        from app.models.embedding import EntryEmbedding

        await self.db.execute(delete(EntryEmbedding).where(EntryEmbedding.entry_id == entry_id))

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
        salt = os.urandom(_SALT_SIZE)
        # KDF + AES off the event loop — see encrypt_entry.
        key = await asyncio.to_thread(self._derive_key_scrypt, passphrase, salt)
        note.body = await asyncio.to_thread(self._encrypt, note.body.encode(), key)
        note.encryption_salt = _KDF_V2_PREFIX + base64.b64encode(salt).decode()
        note.is_encrypted = True
        note.encrypted_at = datetime.now(timezone.utc)
        # Same reasoning as encrypt_entry: the semantic index must not keep a
        # plaintext-derived vector of exactly the text that was just hidden
        # (invertible via a search oracle). The note's FTS row is already
        # handled by the notes_fts triggers.
        await self.db.execute(delete(NoteEmbedding).where(NoteEmbedding.note_id == note.id))
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def decrypt_note(self, note_id: int, passphrase: str) -> Note:
        """Decrypt a note's body in-place."""
        note = await self._get_note(note_id)
        if not note.is_encrypted:
            raise ValueError("Note is not encrypted")
        key = await asyncio.to_thread(
            self._derive_key_for_decrypt, passphrase, note.encryption_salt
        )
        note.body = (await asyncio.to_thread(self._decrypt, note.body, key)).decode()
        note.encryption_salt = None
        note.is_encrypted = False
        note.encrypted_at = None
        await self.db.commit()
        await self.db.refresh(note)
        # The body is plaintext at rest again. Re-index it into the semantic
        # store now — notes have no background backfill sweep, so without this
        # a decrypted note would stay invisible to semantic search until its
        # next save (entries rely on the enrichment sweep instead).
        try:
            from app.services.enrichment_service import EnrichmentService

            EnrichmentService.schedule_note(note.id, note.title, note.body)
        except Exception:
            logger.warning(
                "Failed to schedule embedding for decrypted note %d", note_id, exc_info=True
            )
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

    # ── Free text (selection encryption) ──────────────────────────────────

    async def encrypt_free_text(self, text: str, passphrase: str) -> str:
        """Encrypt arbitrary text into a self-describing envelope.

        A selection has no DB row to keep its KDF salt in, so a fresh random
        salt travels *inside* the envelope, in the same ``v2:`` versioned form
        the entry/note rows use:

            ``v2:<base64 salt>:<base64 nonce+ciphertext>``

        Never derive the salt from the passphrase: that makes the derived key a
        pure function of a guessable input and hands an attacker the whole
        dictionary-attack for free.
        """
        salt = os.urandom(_SALT_SIZE)
        key = await asyncio.to_thread(self._derive_key_scrypt, passphrase, salt)
        token = await asyncio.to_thread(self._encrypt, text.encode(), key)
        return f"{_KDF_V2_PREFIX}{base64.b64encode(salt).decode()}:{token}"

    async def decrypt_free_text(self, envelope: str, passphrase: str) -> str:
        """Decrypt an :meth:`encrypt_free_text` envelope (or a legacy one).

        Legacy envelopes (pre-salted, ``v2:``-less base64 of nonce+ciphertext)
        still decrypt via the old deterministic-salt KDF so no previously
        encrypted selection becomes unreadable.
        """
        if envelope.startswith(_KDF_V2_PREFIX):
            # "v2:<salt_b64>:<nonce+ciphertext>" — base64 never contains ':',
            # so one split separates the salt from the token.
            salt_part, token = envelope[len(_KDF_V2_PREFIX) :].split(":", 1)
            salt = base64.b64decode(salt_part)
            key = await asyncio.to_thread(self._derive_key_scrypt, passphrase, salt)
        else:
            token = envelope
            key = await asyncio.to_thread(self._derive_key_for_decrypt, passphrase, None)
        return (await asyncio.to_thread(self._decrypt, token, key)).decode()
