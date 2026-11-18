"""An AI provider config (OpenAI-compatible cloud, or local Ollama).

``api_key_encrypted`` holds AES-GCM ciphertext (see ``app/core/security.py``);
it is never returned by the API (responses expose only ``has_key``). At most one
row has ``is_active`` — the active provider is what the AI tools route through.
A ``None`` active provider (or an ``ollama`` preset) means "use local Ollama".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # openai | groq | openrouter | kimi | gemini | ollama | custom
    preset: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
