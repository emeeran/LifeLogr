"""Pydantic schemas for AI provider configs.

``api_key`` is accepted on create/update as plaintext (encrypted server-side)
and never returned — responses expose only ``has_key``.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator


def _strip(value: str | None) -> str | None:
    """Trim surrounding whitespace. Returns ``None`` unchanged (means "not set")."""
    if value is None:
        return None
    return value.strip()


def _normalize_base_url(value: str | None) -> str | None:
    """Trim whitespace and any trailing slash; require an http(s) URL with a host.

    The trailing-slash strip handles ``…/v1//chat/completions`` (double slash),
    which some OpenAI-compatible servers reject with a 404 — silently and only
    for the affected provider. The scheme/host check mirrors the Ollama URL
    validation in the settings router: the stored key is later sent to this
    base_url as a Bearer header, so anything that is not a usable HTTP(S)
    endpoint must be rejected at the boundary, not at request time.
    """
    if value is None:
        return None
    url = value.strip().rstrip("/")
    if urlparse(url).scheme.lower() not in ("http", "https"):
        raise ValueError("Base URL must use http or https")
    if not urlparse(url).hostname:
        raise ValueError("Base URL has no host")
    return url


class AIProviderCreate(BaseModel):
    name: str
    preset: str
    base_url: str
    model: str
    api_key: str | None = None
    is_active: bool = False

    _strip_name = field_validator("name", mode="before")(_strip)
    _strip_model = field_validator("model", mode="before")(_strip)
    _norm_base_url = field_validator("base_url", mode="before")(_normalize_base_url)
    # A pasted key with a trailing newline/space is the most common cause of a
    # mysterious 401 — strip before encrypting so it never reaches the provider.
    _strip_api_key = field_validator("api_key", mode="before")(_strip)


class AIProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # if provided, the key is re-encrypted
    is_active: bool | None = None

    _strip_name = field_validator("name", mode="before")(_strip)
    _strip_model = field_validator("model", mode="before")(_strip)
    _norm_base_url = field_validator("base_url", mode="before")(_normalize_base_url)
    _strip_api_key = field_validator("api_key", mode="before")(_strip)


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


class ProviderModelsRequest(BaseModel):
    """List models from an arbitrary endpoint — used by the Add form to browse a
    provider's models *before* it is saved (the per-id ``GET /providers/{id}/models``
    only works for existing providers). Same shape/validators as create/update."""

    base_url: str
    api_key: str | None = None

    _norm_base_url = field_validator("base_url", mode="before")(_normalize_base_url)
    _strip_api_key = field_validator("api_key", mode="before")(_strip)
