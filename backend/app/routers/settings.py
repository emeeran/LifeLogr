"""Application settings route handlers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entry import Entry
from app.models.media import Media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ── Schemas ──────────────────────────────────────────────────────────────


class AISettings(BaseModel):
    ollama_model: str
    ollama_base_url: str
    ollama_embed_model: str
    enable_embeddings: bool
    enable_tag_suggestions: bool
    enable_sentiment: bool
    enable_summarization: bool
    enable_reflection_prompts: bool
    enable_writer_block_helper: bool


class StorageInfo(BaseModel):
    db_size_bytes: int
    media_count: int
    media_size_bytes: int
    entry_count: int


class AppSettingsResponse(BaseModel):
    ai: AISettings
    storage: StorageInfo
    version: str
    app_name: str


class AISettingsUpdate(BaseModel):
    ollama_model: str | None = None
    enable_embeddings: bool | None = None
    enable_tag_suggestions: bool | None = None
    enable_sentiment: bool | None = None
    enable_summarization: bool | None = None
    enable_reflection_prompts: bool | None = None
    enable_writer_block_helper: bool | None = None


class SettingsUpdateRequest(BaseModel):
    ai: AISettingsUpdate | None = None


# ── Helpers ──────────────────────────────────────────────────────────────


def _dir_size(path: Path) -> int:
    """Recursively compute total file size under a directory."""
    total = 0
    if path.is_dir():
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
    return total


def _db_file_size() -> int:
    """Return the SQLite database file size in bytes."""
    p = settings.db_path
    return p.stat().st_size if p.exists() else 0


def _get_ai_settings() -> AISettings:
    return AISettings(
        ollama_model=settings.OLLAMA_MODEL,
        ollama_base_url=settings.OLLAMA_BASE_URL,
        ollama_embed_model=settings.OLLAMA_EMBED_MODEL,
        enable_embeddings=settings.AI_ENABLE_EMBEDDINGS,
        enable_tag_suggestions=settings.AI_ENABLE_TAG_SUGGESTIONS,
        enable_sentiment=settings.AI_ENABLE_SENTIMENT,
        enable_summarization=settings.AI_ENABLE_SUMMARIZATION,
        enable_reflection_prompts=settings.AI_ENABLE_REFLECTION_PROMPTS,
        enable_writer_block_helper=settings.AI_ENABLE_WRITER_BLOCK_HELPER,
    )


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("", response_model=AppSettingsResponse)
async def get_app_settings(db: AsyncSession = Depends(get_db)) -> Any:
    """Return current application settings and storage info."""
    entry_count = (
        await db.execute(select(func.count()).select_from(Entry).where(~Entry.is_deleted))
    ).scalar() or 0

    media_count = (await db.execute(select(func.count()).select_from(Media))).scalar() or 0

    return AppSettingsResponse(
        ai=_get_ai_settings(),
        storage=StorageInfo(
            db_size_bytes=_db_file_size(),
            media_count=media_count,
            media_size_bytes=_dir_size(settings.MEDIA_DIR),
            entry_count=entry_count,
        ),
        version="0.1.0",
        app_name=settings.APP_NAME,
    )


@router.put("")
async def update_app_settings(data: SettingsUpdateRequest) -> dict[str, str]:
    """Update mutable runtime settings (AI feature flags, model)."""
    if data.ai:
        mapping = {
            "ollama_model": "OLLAMA_MODEL",
            "enable_embeddings": "AI_ENABLE_EMBEDDINGS",
            "enable_tag_suggestions": "AI_ENABLE_TAG_SUGGESTIONS",
            "enable_sentiment": "AI_ENABLE_SENTIMENT",
            "enable_summarization": "AI_ENABLE_SUMMARIZATION",
            "enable_reflection_prompts": "AI_ENABLE_REFLECTION_PROMPTS",
            "enable_writer_block_helper": "AI_ENABLE_WRITER_BLOCK_HELPER",
        }
        for field, attr in mapping.items():
            val = getattr(data.ai, field, None)
            if val is not None:
                setattr(settings, attr, val)
    return {"status": "ok"}


@router.get("/models")
async def list_ollama_models() -> list[dict[str, Any]]:
    """List installed Ollama models."""
    import httpx

    models: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    models.append(
                        {
                            "name": m.get("name", ""),
                            "size": m.get("size", 0),
                        }
                    )
    except Exception:
        logger.warning("Failed to fetch Ollama models", exc_info=True)
    return models
