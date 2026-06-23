"""EmbeddingService — retrieve entry embeddings."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding


class EmbeddingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_embedding(self, entry_id: int) -> list[float] | None:
        """Retrieve the embedding vector for an entry."""
        result = await self.db.execute(
            select(EntryEmbedding.embedding).where(EntryEmbedding.entry_id == entry_id)
        )
        row = result.scalar_one_or_none()
        if row:
            return list(json.loads(row))
        return None
