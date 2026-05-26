"""EmbeddingService — CRUD and similarity search for entry embeddings."""

from __future__ import annotations

import json

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.services.enrichment_service import cosine_similarity


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

    async def find_similar(self, entry_id: int, top_k: int = 5) -> list[tuple[int, float]]:
        """Find the top-K most similar entries by cosine similarity."""
        target_vec = await self.get_embedding(entry_id)
        if not target_vec:
            return []

        # Load all embeddings except the target
        result = await self.db.execute(
            select(EntryEmbedding.entry_id, EntryEmbedding.embedding).where(
                EntryEmbedding.entry_id != entry_id
            )
        )
        similarities = []
        for row in result:
            vec = json.loads(row.embedding)
            score = cosine_similarity(target_vec, vec)
            similarities.append((row.entry_id, score))

        # Sort by similarity descending, return top-K
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    async def entry_has_embedding(self, entry_id: int) -> bool:
        """Check if an entry has a stored embedding."""
        result = await self.db.execute(
            select(EntryEmbedding.id).where(EntryEmbedding.entry_id == entry_id)
        )
        return result.scalar_one_or_none() is not None

    async def delete_embedding(self, entry_id: int) -> None:
        """Delete an entry's embedding."""
        await self.db.execute(delete(EntryEmbedding).where(EntryEmbedding.entry_id == entry_id))
        await self.db.commit()
