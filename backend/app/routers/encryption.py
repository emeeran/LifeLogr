"""Encryption route handlers — encrypt/decrypt journal entries and text selection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.encryption import (
    DecryptRequest,
    DecryptTextRequest,
    EncryptionStatusResponse,
    EncryptRequest,
    EncryptTextRequest,
    NoteEncryptionStatusResponse,
)
from app.services.encryption_service import EncryptionService

router = APIRouter(prefix="/api/v1/entries/{entry_id}/encryption", tags=["encryption"])
global_router = APIRouter(prefix="/api/v1/encryption", tags=["encryption"])
notes_router = APIRouter(prefix="/api/v1/notes/{note_id}/encryption", tags=["encryption"])


@router.post("/encrypt", response_model=EncryptionStatusResponse)
async def encrypt_entry(
    entry_id: int, data: EncryptRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Encrypt an entry's title, body, and mood with AES-256-GCM."""
    svc = EncryptionService(db)
    entry = await svc.encrypt_entry(entry_id, data.passphrase)
    return {
        "entry_id": entry.id,
        "is_encrypted": entry.is_encrypted,
        "encrypted_at": entry.encrypted_at,
    }


@router.post("/decrypt", response_model=EncryptionStatusResponse)
async def decrypt_entry(
    entry_id: int, data: DecryptRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Decrypt an entry that was previously encrypted."""
    svc = EncryptionService(db)
    try:
        entry = await svc.decrypt_entry(entry_id, data.passphrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "entry_id": entry.id,
        "is_encrypted": entry.is_encrypted,
        "encrypted_at": entry.encrypted_at,
    }


@router.get("/status", response_model=EncryptionStatusResponse)
async def encryption_status(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Check whether an entry is currently encrypted."""
    svc = EncryptionService(db)
    return await svc.get_encryption_status(entry_id)


# ── Note Encryption ───────────────────────────────────────────────────────────


@notes_router.post("/encrypt", response_model=NoteEncryptionStatusResponse)
async def encrypt_note(
    note_id: int, data: EncryptRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Encrypt a note's body with AES-256-GCM (title stays readable)."""
    svc = EncryptionService(db)
    try:
        note = await svc.encrypt_note(note_id, data.passphrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "note_id": note.id,
        "is_encrypted": note.is_encrypted,
        "encrypted_at": note.encrypted_at,
    }


@notes_router.post("/decrypt", response_model=NoteEncryptionStatusResponse)
async def decrypt_note(
    note_id: int, data: DecryptRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """Decrypt a note that was previously encrypted."""
    svc = EncryptionService(db)
    try:
        note = await svc.decrypt_note(note_id, data.passphrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "note_id": note.id,
        "is_encrypted": note.is_encrypted,
        "encrypted_at": note.encrypted_at,
    }


@notes_router.get("/status", response_model=NoteEncryptionStatusResponse)
async def note_encryption_status(note_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Check whether a note is currently encrypted."""
    svc = EncryptionService(db)
    return await svc.get_note_encryption_status(note_id)


# ── Selection Encryption ──────────────────────────────────────────────────────


@global_router.post("/encrypt-text")
async def encrypt_text(data: EncryptTextRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Encrypt arbitrary text (a journal selection) with a passphrase.

    Uses the salted scrypt KDF; the envelope returned carries its own salt (see
    ``EncryptionService.encrypt_free_text``). Encryption is refused outright
    while the app is running on the public default SECRET_KEY — encryption
    features must not be available on a run that hasn't been keyed.
    """
    from app.core.security import DefaultSecretKeyError, ensure_custom_secret_key

    try:
        ensure_custom_secret_key(allow_test_env=False)
    except DefaultSecretKeyError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    svc = EncryptionService(db)
    encrypted = await svc.encrypt_free_text(data.text, data.passphrase)
    return {"encrypted": encrypted}


@global_router.post("/decrypt-text")
async def decrypt_text(data: DecryptTextRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Decrypt arbitrary text with a passphrase.

    Deliberately *not* gated on the SECRET_KEY: the key is derived from the
    passphrase alone, and blocking decryption would only lock a user out of
    text they can no longer read.
    """
    svc = EncryptionService(db)
    try:
        decrypted = await svc.decrypt_free_text(data.encrypted_text, data.passphrase)
        return {"decrypted": decrypted}
    except Exception:
        raise HTTPException(
            status_code=400, detail="Decryption failed. Check your passphrase and try again."
        )
