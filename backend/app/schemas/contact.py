"""Pydantic schemas for contacts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def _normalize_email(addr: str) -> str:
    """Lowercase and trim an email address for storage as the dedup key."""
    return addr.strip().lower()


class ContactCreate(BaseModel):
    """Create a contact manually."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr
    emails_extra: list[str] | None = None
    phone: str | None = Field(default=None, max_length=50)
    phone_secondary: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    model_config = ConfigDict(json_schema_extra={
        "example": {"name": "Ada Lovelace", "email": "ada@example.com", "company": "Analytical Inc."}
    })


class ContactUpdate(BaseModel):
    """Update an existing contact."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    emails_extra: list[str] | None = None
    phone: str | None = Field(default=None, max_length=50)
    phone_secondary: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ContactResponse(BaseModel):
    """A contact with its current state."""

    id: int
    name: str | None
    email: str
    emails_extra: list[str] | None
    phone: str | None
    phone_secondary: str | None
    company: str | None
    title: str | None
    notes: str | None
    source: str
    last_seen_at: datetime | None
    email_account_id: int | None
    photo_path: str | None
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactListResponse(BaseModel):
    """Paginated contact list."""

    items: list[ContactResponse]
    total: int
    offset: int
    limit: int
