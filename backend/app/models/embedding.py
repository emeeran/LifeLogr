"""Embedding ORM models — JSON-encoded vectors backing semantic search.

One table per embedded entity kind (``EntryEmbedding`` / ``NoteEmbedding``)
rather than a discriminator column on a shared table: the FK target differs per
kind, the per-entity ``unique`` owner constraint gives the cascade/index
behaviour for free, and the semantic cache is keyed by (kind, id) anyway.
Both tables store the *same* model's vectors (``settings.OLLAMA_EMBED_MODEL``
at write time, recorded in ``model_name``), so entry and note vectors live in
one vector space and a query embedding can be compared against either.
"""

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


class NoteEmbedding(Base):
    """Vector for a note's ``title + body`` (the same text ``notes_fts`` indexes).

    Never written for an encrypted note — the body column then holds ciphertext,
    so there is no plaintext to embed and a stale plaintext-derived vector from
    before encryption would leak exactly what was just hidden.

    Table creation needs no ``_migrate_schema`` entry: ``init_db`` runs
    ``Base.metadata.create_all`` (checkfirst) on every boot *before* the inline
    migrations, so the table self-creates on legacy databases too.
    ``note_id`` is unique — one live vector per note, upserted on save.
    """

    __tablename__ = "note_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), unique=True)
    embedding: Mapped[str] = mapped_column(String, nullable=False)  # JSON-encoded list[float]
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
