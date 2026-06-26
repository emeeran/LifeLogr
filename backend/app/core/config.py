"""Application configuration via pydantic-settings."""

import logging
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """Platform-standard data directory when DIARI_DATA_DIR is not set."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "lifelogr"


_logger = logging.getLogger(__name__)


def _migrate_existing_db(target_db: Path, target_data_dir: Path) -> None:
    """Copy an existing database (and media) into *target_data_dir* on first desktop run.

    Searches the platform-default data directory for a database left by a prior
    dev-mode or older desktop install.  Only runs when *target_db* does not yet
    exist, so this is safe to call on every startup.
    """
    if target_db.exists():
        return  # database already present — nothing to migrate

    # Check the platform-default data dir (what dev mode uses when no .env override)
    legacy_dir = _default_data_dir()
    candidates: list[Path] = [
        legacy_dir / "lifelogr.db",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            _logger.info(
                "Migrating existing database from %s → %s", candidate, target_db
            )
            # Atomic write: copy to .tmp then rename
            tmp = target_db.with_suffix(target_db.suffix + ".tmp")
            try:
                shutil.copy2(str(candidate), str(tmp))
                os.replace(str(tmp), str(target_db))
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise

            # Also migrate media files if they exist
            legacy_media = candidate.parent / "media"
            target_media = target_data_dir / "media"
            if legacy_media.is_dir() and not target_media.exists():
                _logger.info(
                    "Migrating media files from %s → %s", legacy_media, target_media
                )
                shutil.copytree(str(legacy_media), str(target_media))
            return  # migrated successfully


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "LifeLogr"
    APP_VERSION: str = "0.4.2"  # in-app version; keep in sync with pyproject.toml
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-before-production"
    DATABASE_URL: str = ""  # derived from DATA_DIR if empty
    MEDIA_DIR: Path = Path("")  # derived from DATA_DIR if empty
    DATA_DIR: Path = Path("")  # set by Tauri sidecar or defaults to platform dir
    CORS_ORIGINS: str = (
        "http://localhost:5173,tauri://localhost,https://tauri.localhost,http://127.0.0.1:18765"
    )
    MAX_MEDIA_SIZE_BYTES: int = 26_214_400  # 25 MB

    # Google OAuth 2.0 Credentials
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Microsoft OneDrive OAuth
    ONEDRIVE_CLIENT_ID: str = ""
    ONEDRIVE_CLIENT_SECRET: str = ""

    # Dropbox OAuth
    DROPBOX_CLIENT_ID: str = ""
    DROPBOX_CLIENT_SECRET: str = ""

    # Ollama (AI assistance)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_TIMEOUT_SECONDS: int = 300

    # AI feature toggles
    AI_ENABLE_EMBEDDINGS: bool = True
    AI_ENABLE_TAG_SUGGESTIONS: bool = True
    AI_ENABLE_SENTIMENT: bool = True
    AI_ENABLE_SUMMARIZATION: bool = True
    AI_ENABLE_REFLECTION_PROMPTS: bool = True
    AI_ENABLE_WRITER_BLOCK_HELPER: bool = True

    # OCR
    OCR_ENGINE: str = "tesseract"

    # Connection pool (for production PostgreSQL)
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Rate limiting
    RATE_LIMIT: str = "60/minute"

    def model_post_init(self, __context: object) -> None:
        """Resolve derived paths after loading from env."""
        # Resolve DATA_DIR
        if not self.DATA_DIR or str(self.DATA_DIR) == ".":
            self.DATA_DIR = _default_data_dir()
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Derive DATABASE_URL if not explicitly set
        if not self.DATABASE_URL:
            db_path = self.DATA_DIR / "lifelogr.db"
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
            # On first desktop run, migrate existing database from the
            # platform-default data dir (e.g. from dev/prior installs).
            _migrate_existing_db(db_path, self.DATA_DIR)

        # Derive MEDIA_DIR if not explicitly set
        if not self.MEDIA_DIR or str(self.MEDIA_DIR) == ".":
            self.MEDIA_DIR = self.DATA_DIR / "media"
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        """Filesystem path to the SQLite database file."""
        url_str = str(self.DATABASE_URL)
        # SQLAlchemy SQLite URLs: sqlite+aiosqlite:///path
        # 3 slashes = relative, 4 slashes = absolute.  urlparse does NOT
        # handle this correctly for SQLite's non-standard URL scheme, so
        # we strip the scheme prefix manually.
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url_str.startswith(prefix):
                return Path(url_str[len(prefix):])
        return Path(urlparse(url_str).path)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate_production(self) -> None:
        """Validate critical settings when running in production.

        Only enforced for server deployments (Docker, cloud). Desktop/Tauri
        sidecar runs locally with no external access — validation is skipped.
        """
        if self.is_production and self.SECRET_KEY == "change-me-before-production":
            raise RuntimeError("SECRET_KEY must be changed in production. Set it in .env")


settings = Settings()
