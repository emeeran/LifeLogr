"""Encryption route handlers — encrypt/decrypt journal entries and text selection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.encryption import (
    DecryptRequest,
    DecryptTextRequest,
    EncryptRequest,
    EncryptTextRequest,
    EncryptionStatusResponse,
)
from app.services.encryption_service import EncryptionService

router = APIRouter(prefix="/api/v1/entries/{entry_id}/encryption", tags=["encryption"])
global_router = APIRouter(prefix="/api/v1/encryption", tags=["encryption"])


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
    entry = await svc.decrypt_entry(entry_id, data.passphrase)
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


# ── Selection Encryption ──────────────────────────────────────────────────────


@global_router.post("/encrypt-text")
async def encrypt_text(data: EncryptTextRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Encrypt arbitrary text with a passphrase."""
    svc = EncryptionService(db)
    # Expose private helper for selection encryption
    key = svc._derive_key(data.passphrase)
    encrypted = svc._encrypt(data.text.encode(), key)
    return {"encrypted": encrypted}


@global_router.post("/decrypt-text")
async def decrypt_text(data: DecryptTextRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Decrypt arbitrary text with a passphrase."""
    svc = EncryptionService(db)
    try:
        key = svc._derive_key(data.passphrase)
        decrypted = svc._decrypt(data.encrypted_text, key).decode()
        return {"decrypted": decrypted}
    except Exception:
        raise HTTPException(
            status_code=400, detail="Decryption failed. Check your passphrase and try again."
        )
