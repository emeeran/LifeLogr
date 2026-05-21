"""Application configuration via pydantic-settings."""
import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """Platform-standard data directory when DIARI_DATA_DIR is not set."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "diarilinux"


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "Diarilinux"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-before-production"
    DATABASE_URL: str = ""  # derived from DATA_DIR if empty
    MEDIA_DIR: Path = Path("")  # derived from DATA_DIR if empty
    DATA_DIR: Path = Path("")  # set by Tauri sidecar or defaults to platform dir
    CORS_ORIGINS: str = "http://localhost:5173,tauri://localhost,https://tauri.localhost,http://127.0.0.1:18765"
    MAX_MEDIA_SIZE_BYTES: int = 26_214_400  # 25 MB

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

    # Whisper (voice-to-text)
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"

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
            db_path = self.DATA_DIR / "diarilinux.db"
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

        # Derive MEDIA_DIR if not explicitly set
        if not self.MEDIA_DIR or str(self.MEDIA_DIR) == ".":
            self.MEDIA_DIR = self.DATA_DIR / "media"
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)

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
