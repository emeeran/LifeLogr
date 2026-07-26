"""AI provider configs (OpenAI-compatible cloud providers + local Ollama).

All listed cloud providers (OpenAI, Groq, OpenRouter, Kimi/Moonshot, Gemini via
Google's OpenAI-compatible endpoint) speak the OpenAI chat-completions API, so
one adapter covers them. Keys are AES-GCM encrypted at rest
(``app/core/security.py``) and never returned by the API. The *active* provider
is what :class:`app.services.ollama_service.OllamaService` routes through; if
none is active (or it's the ``ollama`` preset), local Ollama is used.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.models.ai_provider import AIProvider
from app.schemas.ai_provider import AIProviderCreate, AIProviderUpdate

# key → {label, default base_url, default model}. Shared with the frontend via
# GET /api/v1/ai/providers/presets.
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434",
        "model": "llama3.2:3b",
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "base_url": "",
        "model": "",
    },
}


class AIProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self) -> list[AIProvider]:
        res = await self.db.execute(select(AIProvider).order_by(AIProvider.created_at))
        return list(res.scalars())

    async def create(self, data: AIProviderCreate) -> AIProvider:
        provider = AIProvider(
            name=data.name,
            preset=data.preset,
            base_url=data.base_url,
            model=data.model,
            api_key_encrypted=security.encrypt(data.api_key) if data.api_key else None,
            is_active=data.is_active,
        )
        self.db.add(provider)
        await self.db.flush()
        if data.is_active:
            await self._set_only_active(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        invalidate_active_cache()
        return provider

    async def update(self, provider_id: int, data: AIProviderUpdate) -> AIProvider:
        provider = await self._get(provider_id)
        if data.name is not None:
            provider.name = data.name
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.model is not None:
            provider.model = data.model
        if data.api_key is not None:
            provider.api_key_encrypted = security.encrypt(data.api_key)
        if data.is_active is not None:
            provider.is_active = data.is_active
            if data.is_active:
                await self._set_only_active(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        invalidate_active_cache()
        return provider

    async def delete(self, provider_id: int) -> None:
        provider = await self._get(provider_id)
        await self.db.delete(provider)
        await self.db.commit()
        invalidate_active_cache()

    async def activate(self, provider_id: int) -> AIProvider:
        provider = await self._get(provider_id)
        await self._set_only_active(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        invalidate_active_cache()
        return provider

    async def _get(self, provider_id: int) -> AIProvider:
        res = await self.db.execute(select(AIProvider).where(AIProvider.id == provider_id))
        provider = res.scalar_one_or_none()
        if provider is None:
            raise ValueError(f"AI provider {provider_id} not found")
        return provider

    async def _set_only_active(self, provider: AIProvider) -> None:
        provider.is_active = True
        await self.db.execute(
            update(AIProvider)
            .where(AIProvider.id != provider.id, AIProvider.is_active == True)  # noqa: E712
            .values(is_active=False)
        )


# ── Active-provider cache (avoids a DB read on every AI call) ──
_UNSET: Any = object()
_active_cache: Any = _UNSET


async def get_active_provider() -> AIProvider | None:
    """The active AI provider, or ``None`` (→ local Ollama fallback). Cached."""
    global _active_cache
    if _active_cache is not _UNSET:
        return cast(AIProvider | None, _active_cache)
    from app.core.database import async_session

    async with async_session() as session:
        res = await session.execute(
            select(AIProvider).where(AIProvider.is_active == True).limit(1)  # noqa: E712
        )
        provider = res.scalar_one_or_none()
    _active_cache = provider
    return provider


def invalidate_active_cache() -> None:
    """Clear the cached active provider (call after any provider change)."""
    global _active_cache
    _active_cache = _UNSET


async def test_connection(base_url: str, api_key: str | None, model: str) -> str:
    """Probe an OpenAI-compatible endpoint with a 1-token completion.

    Returns the model string the server reports on success; raises
    ``httpx.HTTPError`` on failure (the router maps it to an error response).
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            headers=headers,
        )
        resp.raise_for_status()
        return str(resp.json().get("model") or model)


async def list_models(base_url: str, api_key: str | None) -> list[dict[str, str]]:
    """List the models an OpenAI-compatible endpoint exposes (``GET /models``).

    Every cloud preset speaks this (OpenAI/Groq/OpenRouter/Kimi, and Gemini's
    ``/v1beta/openai/models``). Returns ``[{"id", "owned_by"}, ...]`` sorted by
    id. Raises ``httpx.HTTPError`` on failure (the router surfaces the body).
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
        resp = await client.get(f"{base_url}/models", headers=headers)
        resp.raise_for_status()
    data = resp.json().get("data") or []
    models = [
        {"id": str(m["id"]), "owned_by": str(m.get("owned_by", ""))}
        for m in data
        if m.get("id")
    ]
    models.sort(key=lambda m: m["id"])
    return models
