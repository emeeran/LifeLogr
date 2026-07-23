"""Application configuration via pydantic-settings."""

import json
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


def _config_dir() -> Path:
    """Platform-standard *config* directory (outside DATA_DIR).

    Holds the storage-path override so it survives DATA_DIR moves. Mirrors
    ``_default_data_dir``'s platform branches but points at the config area,
    never inside the data area.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "lifelogr" / "config"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "lifelogr"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "lifelogr"


_logger = logging.getLogger(__name__)


_STORAGE_OVERRIDE_FILENAME = "data-location.json"


def _storage_override_path() -> Path:
    """Path to the persisted storage-location override file."""
    return _config_dir() / _STORAGE_OVERRIDE_FILENAME


def _read_storage_override() -> Path | None:
    """Return the user-chosen DATA_DIR from the override file, or ``None``.

    Stored outside DATA_DIR (in the config dir) so it survives relocation.
    Only absolute paths are honoured; malformed entries are ignored.
    """
    path = _storage_override_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text()).get("data_dir")
            if raw:
                candidate = Path(raw).expanduser()
                if candidate.is_absolute():
                    return candidate
    except Exception:
        _logger.warning("Could not read storage override %s", path, exc_info=True)
    return None


def write_storage_override(data_dir: Path) -> None:
    """Persist the user-chosen DATA_DIR so it survives restarts.

    Honoured (with identical precedence) by the launcher in
    ``scripts/build-web-deb.sh``.
    """
    path = _storage_override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data_dir": str(Path(data_dir).expanduser())}))


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
            _logger.info("Migrating existing database from %s → %s", candidate, target_db)
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
                _logger.info("Migrating media files from %s → %s", legacy_media, target_media)
                shutil.copytree(str(legacy_media), str(target_media))
            return  # migrated successfully


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "LifeLogr"
    APP_VERSION: str = "0.7.1"  # in-app version; keep in sync with pyproject.toml
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-before-production"
    DATABASE_URL: str = ""  # derived from DATA_DIR if empty
    MEDIA_DIR: Path = Path("")  # derived from DATA_DIR if empty
    DATA_DIR: Path = Path("")  # set by Tauri sidecar or defaults to platform dir
    TTS_CACHE_DIR: Path = Path("")  # derived from DATA_DIR if empty
    CORS_ORIGINS: str = (
        "http://localhost:5173,tauri://localhost,"
        "http://tauri.localhost,https://tauri.localhost,http://127.0.0.1:18765"
    )
    MAX_MEDIA_SIZE_BYTES: int = 26_214_400  # 25 MB
    # Hard ceiling on a restored .tar.gz upload — the import streams to disk and
    # aborts with 413 past this, so an unauthenticated loopback request can't
    # exhaust memory by streaming a huge payload at /backup/import.
    MAX_IMPORT_SIZE_BYTES: int = 2 * 1024**3  # 2 GiB
    # Comma-separated extra roots a local backup may target beyond the defaults
    # (home, app data dir, temp dir) — e.g. "/media,/mnt" for external drives.
    BACKUP_ALLOWED_ROOTS: str = ""

    # Email client defaults (IMAP/SMTP polling sync)
    EMAIL_SYNC_INTERVAL_MINUTES: int = 10
    EMAIL_MAX_ATTACHMENT_SIZE_BYTES: int = 26_214_400  # 25 MB
    EMAIL_SYNC_ON_STARTUP: bool = True
    EMAIL_INITIAL_SYNC_BATCH: int = 100  # messages per FETCH round-trip

    # Google Calendar+Tasks two-way sync (mail is separate, on IMAP).
    GOOGLE_SYNC_INTERVAL_MINUTES: int = 15

    # Google OAuth 2.0 Credentials
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Microsoft OneDrive OAuth
    ONEDRIVE_CLIENT_ID: str = ""
    ONEDRIVE_CLIENT_SECRET: str = ""

    # Dropbox OAuth
    DROPBOX_CLIENT_ID: str = ""
    DROPBOX_CLIENT_SECRET: str = ""

    # Box OAuth
    BOX_CLIENT_ID: str = ""
    BOX_CLIENT_SECRET: str = ""

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
        # Resolve DATA_DIR. Precedence (kept in sync with the launcher in
        # scripts/build-web-deb.sh): explicit LIFELOGR_DATA_DIR env >
        # persisted storage-path override (user UI choice, stored outside
        # DATA_DIR so it survives moves) > DATA_DIR env / platform default.
        env_data_dir = os.environ.get("LIFELOGR_DATA_DIR")
        if env_data_dir:
            self.DATA_DIR = Path(env_data_dir)
        else:
            override = _read_storage_override()
            if override is not None:
                self.DATA_DIR = override
            elif not self.DATA_DIR or str(self.DATA_DIR) == ".":
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

        # Derive TTS_CACHE_DIR — cached read-aloud audio served via FileResponse
        # (Range-capable) so playback is instant on repeat and reliable in Tauri.
        if not self.TTS_CACHE_DIR or str(self.TTS_CACHE_DIR) == ".":
            self.TTS_CACHE_DIR = self.DATA_DIR / "tts"
        self.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
                return Path(url_str[len(prefix) :])
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
