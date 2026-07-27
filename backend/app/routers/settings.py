"""Application settings route handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.settings_service import (
    db_file_size,
    dir_size,
    persist_runtime_settings,
    storage_info,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# Runtime-settings persistence + storage reporting live in
# ``app.services.settings_service`` (keeps file/DB side effects out of the
# router). Startup loads via ``load_runtime_settings`` (see app.main).


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
    ollama_base_url: str | None = None
    ollama_embed_model: str | None = None
    enable_embeddings: bool | None = None
    enable_tag_suggestions: bool | None = None
    enable_sentiment: bool | None = None
    enable_summarization: bool | None = None
    enable_reflection_prompts: bool | None = None
    enable_writer_block_helper: bool | None = None


class SettingsUpdateRequest(BaseModel):
    ai: AISettingsUpdate | None = None


class StoragePathResponse(BaseModel):
    data_dir: str
    db_path: str
    db_size_bytes: int
    media_size_bytes: int


class StoragePathUpdate(BaseModel):
    data_dir: str


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
    info = await storage_info(db)
    return AppSettingsResponse(
        ai=_get_ai_settings(),
        storage=StorageInfo(**info),
        version=settings.APP_VERSION,
        app_name=settings.APP_NAME,
    )


@router.put("")
async def update_app_settings(data: SettingsUpdateRequest) -> dict[str, str]:
    """Update mutable runtime settings (AI feature flags, model)."""
    if data.ai:
        # The Ollama URL is user-settable and proxies journal content to an
        # arbitrary host — restrict it to http(s) to block obvious SSRF.
        if data.ai.ollama_base_url is not None:
            from urllib.parse import urlparse

            from fastapi import HTTPException

            if urlparse(data.ai.ollama_base_url).scheme.lower() not in ("http", "https"):
                raise HTTPException(
                    status_code=400, detail="Ollama URL must use http or https"
                )
        mapping = {
            "ollama_model": "OLLAMA_MODEL",
            "ollama_base_url": "OLLAMA_BASE_URL",
            "ollama_embed_model": "OLLAMA_EMBED_MODEL",
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
        persist_runtime_settings()
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


@router.post("/vacuum")
async def vacuum_database(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run VACUUM to compact the SQLite database and reclaim disk space."""
    before = db_file_size()
    await db.execute(text("VACUUM"))
    after = db_file_size()
    return {"status": "ok", "reclaimed_bytes": before - after}


@router.post("/integrity-check")
async def integrity_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run SQLite integrity check on the database."""
    result = await db.execute(text("PRAGMA integrity_check"))
    row = result.scalar()
    ok = row == "ok"
    return {"status": "ok" if ok else "error", "message": row}


@router.get("/storage-path", response_model=StoragePathResponse)
async def get_storage_path() -> Any:
    """Return the active data directory and disk usage."""
    return StoragePathResponse(
        data_dir=str(settings.DATA_DIR),
        db_path=str(settings.db_path),
        db_size_bytes=db_file_size(),
        media_size_bytes=dir_size(settings.MEDIA_DIR),
    )


@router.post("/storage-path")
async def update_storage_path(
    data: StoragePathUpdate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Relocate the data directory to *data_dir* (hot-move, no restart).

    Copies DB + media + secrets, swaps the live engine, and persists the choice
    so it survives restart. Raises 400 on an invalid target or insufficient
    space. The old directory is left intact.
    """
    from fastapi import HTTPException

    from app.services.storage_service import relocate_storage

    try:
        result = await relocate_storage(data.data_dir, session=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", **result}
