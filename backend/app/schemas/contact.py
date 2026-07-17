"""Pydantic schemas for contacts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def _normalize_email(addr: str) -> str:
    """Lowercase and trim an email address for storage as the dedup key."""
    return addr.strip().lower()


# ── Reusable structured field blocks (EPIM-style) ────────────────────────────


class TypedValue(BaseModel):
    """A typed multi-value entry — phones, IM handles, relationships."""

    type: str
    value: str


class AddressValue(BaseModel):
    """A structured postal address."""

    type: str = "home"
    street: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None


class DateValue(BaseModel):
    """A dated event (birthday, anniversary, …). ``date`` is an ISO date."""

    type: str = "birthday"
    label: str | None = None
    date: str


# ── Groups ───────────────────────────────────────────────────────────────────


class ContactGroupBrief(BaseModel):
    id: int
    name: str
    color: str | None

    model_config = ConfigDict(from_attributes=True)


class ContactGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    color: str | None = Field(default=None, max_length=32)
    sort_order: int = 0


class ContactGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = Field(default=None, max_length=32)
    sort_order: int | None = None


class ContactGroupResponse(BaseModel):
    id: int
    name: str
    color: str | None
    sort_order: int
    member_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Related emails ───────────────────────────────────────────────────────────


class RelatedEmailResponse(BaseModel):
    id: int
    account_id: int
    subject: str | None
    from_address: str
    from_name: str | None
    sent_at: datetime | None
    is_read: bool

    model_config = ConfigDict(from_attributes=True)


# ── Contacts ─────────────────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    """Create a contact manually."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr
    emails_extra: list[str] | None = None
    phone: str | None = Field(default=None, max_length=50)
    phone_secondary: str | None = Field(default=None, max_length=50)
    phones: list[TypedValue] | None = None
    company: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    profession: str | None = Field(default=None, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    addresses: list[AddressValue] | None = None
    im_handles: list[TypedValue] | None = None
    websites: list[str] | None = None
    dates: list[DateValue] | None = None
    relationships: list[TypedValue] | None = None
    notes: str | None = None
    is_favorite: bool = False
    group_ids: list[int] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "company": "Analytical Inc.",
            }
        }
    )


class ContactUpdate(BaseModel):
    """Update an existing contact. All fields optional."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    emails_extra: list[str] | None = None
    phone: str | None = Field(default=None, max_length=50)
    phone_secondary: str | None = Field(default=None, max_length=50)
    phones: list[TypedValue] | None = None
    company: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    profession: str | None = Field(default=None, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    addresses: list[AddressValue] | None = None
    im_handles: list[TypedValue] | None = None
    websites: list[str] | None = None
    dates: list[DateValue] | None = None
    relationships: list[TypedValue] | None = None
    notes: str | None = None
    is_favorite: bool | None = None
    group_ids: list[int] | None = None


class ContactResponse(BaseModel):
    """A contact with its current state."""

    id: int
    name: str | None
    email: str
    emails_extra: list[str] | None
    phone: str | None
    phone_secondary: str | None
    phones: list[TypedValue] | None
    company: str | None
    title: str | None
    department: str | None
    profession: str | None
    nickname: str | None
    addresses: list[AddressValue] | None
    im_handles: list[TypedValue] | None
    websites: list[str] | None
    dates: list[DateValue] | None
    relationships: list[TypedValue] | None
    notes: str | None
    is_favorite: bool
    groups: list[ContactGroupBrief]
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
