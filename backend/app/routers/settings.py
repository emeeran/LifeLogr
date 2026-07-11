"""Application settings route handlers."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entry import Entry
from app.models.media import Media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# ── Settings persistence ─────────────────────────────────────────────────


def _settings_file() -> Path:
    """Path to the persisted runtime settings JSON file."""
    return Path(settings.DATA_DIR) / ".runtime-settings.json"


def _persist_settings() -> None:
    """Write current mutable settings to disk so they survive restarts."""
    data = {
        "OLLAMA_MODEL": settings.OLLAMA_MODEL,
        "OLLAMA_BASE_URL": settings.OLLAMA_BASE_URL,
        "OLLAMA_EMBED_MODEL": settings.OLLAMA_EMBED_MODEL,
        "AI_ENABLE_EMBEDDINGS": settings.AI_ENABLE_EMBEDDINGS,
        "AI_ENABLE_TAG_SUGGESTIONS": settings.AI_ENABLE_TAG_SUGGESTIONS,
        "AI_ENABLE_SENTIMENT": settings.AI_ENABLE_SENTIMENT,
        "AI_ENABLE_SUMMARIZATION": settings.AI_ENABLE_SUMMARIZATION,
        "AI_ENABLE_REFLECTION_PROMPTS": settings.AI_ENABLE_REFLECTION_PROMPTS,
        "AI_ENABLE_WRITER_BLOCK_HELPER": settings.AI_ENABLE_WRITER_BLOCK_HELPER,
        "EMAIL_SYNC_INTERVAL_MINUTES": settings.EMAIL_SYNC_INTERVAL_MINUTES,
        "EMAIL_SYNC_ON_STARTUP": settings.EMAIL_SYNC_ON_STARTUP,
    }
    try:
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        _settings_file().write_text(json.dumps(data, indent=2))
    except Exception:
        logger.warning("Failed to persist settings", exc_info=True)


def load_persisted_settings() -> None:
    """Load previously saved runtime settings from disk.

    Called once during app startup. Values here override the defaults
    from .env / environment variables.
    """
    path = _settings_file()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        mapping = {
            "OLLAMA_MODEL": "OLLAMA_MODEL",
            "OLLAMA_BASE_URL": "OLLAMA_BASE_URL",
            "OLLAMA_EMBED_MODEL": "OLLAMA_EMBED_MODEL",
            "AI_ENABLE_EMBEDDINGS": "AI_ENABLE_EMBEDDINGS",
            "AI_ENABLE_TAG_SUGGESTIONS": "AI_ENABLE_TAG_SUGGESTIONS",
            "AI_ENABLE_SENTIMENT": "AI_ENABLE_SENTIMENT",
            "AI_ENABLE_SUMMARIZATION": "AI_ENABLE_SUMMARIZATION",
            "AI_ENABLE_REFLECTION_PROMPTS": "AI_ENABLE_REFLECTION_PROMPTS",
            "AI_ENABLE_WRITER_BLOCK_HELPER": "AI_ENABLE_WRITER_BLOCK_HELPER",
            "EMAIL_SYNC_INTERVAL_MINUTES": "EMAIL_SYNC_INTERVAL_MINUTES",
            "EMAIL_SYNC_ON_STARTUP": "EMAIL_SYNC_ON_STARTUP",
        }
        for json_key, settings_attr in mapping.items():
            if json_key in data:
                setattr(settings, settings_attr, data[json_key])
        logger.info("Loaded persisted settings from %s", path)
    except Exception:
        logger.warning("Failed to load persisted settings", exc_info=True)


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


class EmailSettings(BaseModel):
    sync_interval_minutes: int
    sync_on_startup: bool


class AppSettingsResponse(BaseModel):
    ai: AISettings
    email: EmailSettings
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


class EmailSettingsUpdate(BaseModel):
    sync_interval_minutes: int | None = None
    sync_on_startup: bool | None = None


class SettingsUpdateRequest(BaseModel):
    ai: AISettingsUpdate | None = None
    email: EmailSettingsUpdate | None = None


class StoragePathResponse(BaseModel):
    data_dir: str
    db_path: str
    db_size_bytes: int
    media_size_bytes: int


class StoragePathUpdate(BaseModel):
    data_dir: str


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
        email=EmailSettings(
            sync_interval_minutes=settings.EMAIL_SYNC_INTERVAL_MINUTES,
            sync_on_startup=settings.EMAIL_SYNC_ON_STARTUP,
        ),
        storage=StorageInfo(
            db_size_bytes=_db_file_size(),
            media_count=media_count,
            media_size_bytes=_dir_size(settings.MEDIA_DIR),
            entry_count=entry_count,
        ),
        version=settings.APP_VERSION,
        app_name=settings.APP_NAME,
    )


@router.put("")
async def update_app_settings(data: SettingsUpdateRequest) -> dict[str, str]:
    """Update mutable runtime settings (AI feature flags, model)."""
    if data.ai:
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
        _persist_settings()
    if data.email:
        if data.email.sync_interval_minutes is not None:
            settings.EMAIL_SYNC_INTERVAL_MINUTES = data.email.sync_interval_minutes
        if data.email.sync_on_startup is not None:
            settings.EMAIL_SYNC_ON_STARTUP = data.email.sync_on_startup
        _persist_settings()
        # Re-schedule email sync jobs to pick up the new interval.
        try:
            from app.services.scheduler_service import SchedulerService

            await SchedulerService.sync_email_accounts()
        except Exception:
            logger.debug("Email sync job resync skipped", exc_info=True)
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
    before = _db_file_size()
    await db.execute(text("VACUUM"))
    after = _db_file_size()
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
        db_size_bytes=_db_file_size(),
        media_size_bytes=_dir_size(settings.MEDIA_DIR),
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
