"""Pydantic schemas for AI provider configs.

``api_key`` is accepted on create/update as plaintext (encrypted server-side)
and never returned — responses expose only ``has_key``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIProviderCreate(BaseModel):
    name: str
    preset: str
    base_url: str
    model: str
    api_key: str | None = None
    is_active: bool = False


class AIProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # if provided, the key is re-encrypted
    is_active: bool | None = None


class AIProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    preset: str
    base_url: str
    model: str
    has_key: bool
    is_active: bool
    created_at: datetime


class ProviderPresets(BaseModel):
    """Static provider preset catalogue (label + default base_url/model)."""

    key: str
    label: str
    base_url: str
    model: str
