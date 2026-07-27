"""Runtime settings persistence + storage reporting.

Owns the JSON file that lets the mutable AI/model settings survive restarts
(previously module-level side effects in the settings router) and the storage-
info gathering for the settings response — keeping the router a thin transport
layer with no file/DB side effects at module import time.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media

logger = logging.getLogger(__name__)

# Persisted mutable settings; the JSON key matches the settings attribute name.
PERSISTED_SETTING_FIELDS: tuple[str, ...] = (
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_EMBED_MODEL",
    "AI_ENABLE_EMBEDDINGS",
    "AI_ENABLE_TAG_SUGGESTIONS",
    "AI_ENABLE_SENTIMENT",
    "AI_ENABLE_SUMMARIZATION",
    "AI_ENABLE_REFLECTION_PROMPTS",
    "AI_ENABLE_WRITER_BLOCK_HELPER",
)


def _settings_file() -> Path:
    """Path to the persisted runtime settings JSON file."""
    return Path(settings.DATA_DIR) / ".runtime-settings.json"


def persist_runtime_settings() -> None:
    """Write current mutable settings to disk so they survive restarts."""
    data = {name: getattr(settings, name) for name in PERSISTED_SETTING_FIELDS}
    try:
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        _settings_file().write_text(json.dumps(data, indent=2))
    except Exception:
        logger.warning("Failed to persist settings", exc_info=True)


def load_runtime_settings() -> None:
    """Load previously saved runtime settings from disk.

    Called once during app startup. Values here override the defaults
    from .env / environment variables.
    """
    path = _settings_file()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        for name in PERSISTED_SETTING_FIELDS:
            if name in data:
                setattr(settings, name, data[name])
        logger.info("Loaded persisted settings from %s", path)
    except Exception:
        logger.warning("Failed to load persisted settings", exc_info=True)


def dir_size(path: Path) -> int:
    """Recursively compute total file size under a directory."""
    total = 0
    if path.is_dir():
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += dir_size(Path(entry.path))
    return total


def db_file_size() -> int:
    """Return the SQLite database file size in bytes."""
    p = settings.db_path
    return p.stat().st_size if p.exists() else 0


async def storage_info(db: AsyncSession) -> dict[str, int]:
    """Entry/media counts + on-disk sizes for the settings response."""
    entry_count = (
        await db.execute(select(func.count()).select_from(Entry).where(~Entry.is_deleted))
    ).scalar() or 0
    media_count = (await db.execute(select(func.count()).select_from(Media))).scalar() or 0
    return {
        "db_size_bytes": db_file_size(),
        "media_count": int(media_count),
        "media_size_bytes": dir_size(settings.MEDIA_DIR),
        "entry_count": int(entry_count),
    }
