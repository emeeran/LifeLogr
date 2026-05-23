"""Pydantic schemas for entry encryption."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EncryptRequest(BaseModel):
    """Request to encrypt an entire entry."""
    passphrase: str = Field(min_length=1, description="Passphrase to derive encryption key")

    model_config = ConfigDict(json_schema_extra={
        "example": {"passphrase": "my-secret-passphrase"}
    })


class DecryptRequest(BaseModel):
    """Request to decrypt an entry."""
    passphrase: str = Field(min_length=1, description="Passphrase used during encryption")

    model_config = ConfigDict(json_schema_extra={
        "example": {"passphrase": "my-secret-passphrase"}
    })


class EncryptionStatusResponse(BaseModel):
    """Shows whether an entry is encrypted."""
    entry_id: int
    is_encrypted: bool
    encrypted_at: datetime | None = None


class EntryDecryptedResponse(BaseModel):
    """An entry with its content decrypted."""
    id: int
    entry_date: str
    title: str | None
    body: str
    mood: str | None

    model_config = ConfigDict(from_attributes=True)


class EncryptTextRequest(BaseModel):
    """Request to encrypt arbitrary text."""
    text: str = Field(min_length=1)
    passphrase: str = Field(min_length=1)


class DecryptTextRequest(BaseModel):
    """Request to decrypt arbitrary text."""
    encrypted_text: str = Field(min_length=1)
    passphrase: str = Field(min_length=1)
