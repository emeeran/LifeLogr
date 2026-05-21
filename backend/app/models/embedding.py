"""EntryEmbedding ORM model — stores vector embeddings for semantic search."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EntryEmbedding(Base):
    __tablename__ = "entry_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), unique=True)
    embedding: Mapped[str] = mapped_column(String, nullable=False)  # JSON-encoded list[float]
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
