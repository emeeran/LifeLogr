"""Pydantic schemas for the email module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Accounts ───────────────────────────────────────────────────────────────


class EmailAccountCreate(BaseModel):
    label: str = Field(max_length=100)
    email_address: EmailStr
    imap_host: str = Field(max_length=255)
    imap_port: int = 993
    imap_use_ssl: bool = True
    smtp_host: str = Field(max_length=255)
    smtp_port: int = 587
    smtp_use_tls: bool = True
    username: str = Field(max_length=320)
    password: str  # plaintext from the form; encrypted before storage
    display_name: str | None = Field(default=None, max_length=255)
    poll_interval_minutes: int = 10


class EmailAccountUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    email_address: EmailStr | None = None
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = None
    imap_use_ssl: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = None
    smtp_use_tls: bool | None = None
    username: str | None = Field(default=None, max_length=320)
    password: str | None = None  # if provided, re-encrypt
    display_name: str | None = Field(default=None, max_length=255)
    sync_enabled: bool | None = None
    poll_interval_minutes: int | None = None
    is_active: bool | None = None


class EmailAccountResponse(BaseModel):
    id: int
    label: str
    email_address: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    username: str
    display_name: str | None
    sync_enabled: bool
    poll_interval_minutes: int
    last_synced_at: datetime | None
    last_sync_error: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmailAccountTestResult(BaseModel):
    success: bool
    error: str | None = None


# ── Folders ────────────────────────────────────────────────────────────────


class EmailFolderResponse(BaseModel):
    id: int
    account_id: int
    folder_name: str
    display_name: str | None
    special_use: str | None
    message_count: int
    unread_count: int
    sync_enabled: bool

    model_config = ConfigDict(from_attributes=True)


class EmailFolderUpdate(BaseModel):
    sync_enabled: bool | None = None
    display_name: str | None = Field(default=None, max_length=255)


# ── Attachments ────────────────────────────────────────────────────────────


class EmailAttachmentResponse(BaseModel):
    id: int
    message_id: int
    filename: str
    content_type: str
    file_size: int
    content_id: str | None
    is_inline: bool

    model_config = ConfigDict(from_attributes=True)


# ── Messages ───────────────────────────────────────────────────────────────


class EmailMessageListResponse(BaseModel):
    id: int
    account_id: int
    folder_id: int
    from_address: str
    from_name: str | None
    to_addresses: list[str]
    subject: str | None
    snippet: str | None
    sent_at: datetime | None
    is_read: bool
    is_starred: bool
    has_attachments: bool
    is_spam: bool
    spam_score: float | None

    model_config = ConfigDict(from_attributes=True)


class EmailMessageResponse(EmailMessageListResponse):
    cc_addresses: list[str] | None
    bcc_addresses: list[str] | None
    reply_to: str | None
    text_body: str | None
    html_body: str | None
    in_reply_to: str | None
    is_draft: bool
    attachments: list[EmailAttachmentResponse] = []


class MessageFlagUpdate(BaseModel):
    is_read: bool | None = None
    is_starred: bool | None = None


class MessageSpamUpdate(BaseModel):
    is_spam: bool


class SpamRuleCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)
    is_domain: bool = False
    action: str = Field(default="junk", pattern="^(junk|delete)$")


class SpamRuleResponse(BaseModel):
    id: int
    pattern: str
    is_domain: bool
    action: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BlockSenderRequest(BaseModel):
    """Block the sender of a message, applying the action to existing + future mail."""

    action: str = Field(default="junk", pattern="^(junk|delete)$")
    # "domain" blocks the whole domain (default, broader); "sender" is exact address.
    scope: str = Field(default="domain", pattern="^(domain|sender)$")


class BlockSenderResult(BaseModel):
    rule: SpamRuleResponse
    action: str
    affected: int


class EmailMessageListResult(BaseModel):
    items: list[EmailMessageListResponse]
    total: int
    offset: int
    limit: int


# ── Compose ────────────────────────────────────────────────────────────────


class EmailCompose(BaseModel):
    account_id: int
    to: list[str]
    cc: list[str] | None = None
    bcc: list[str] | None = None
    subject: str = Field(max_length=1000)
    text_body: str = ""
    html_body: str | None = None
    in_reply_to_message_id: int | None = None
    attachment_ids: list[str] = []


class EmailSendResult(BaseModel):
    success: bool
    sent_message_id: int | None = None
    error: str | None = None


class TempAttachmentResponse(BaseModel):
    id: str
    filename: str
    file_size: int
