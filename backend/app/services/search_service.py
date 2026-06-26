"""SearchService — FTS5 full-text search, semantic search, and hybrid search."""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.schemas.search import SearchResultEntry, SearchMode

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(
        self,
        query: str,
        mood: str | None = None,
        tag_ids: list[int] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 20,
        mode: SearchMode = "hybrid",
    ) -> tuple[list[SearchResultEntry], int]:
        """Search entries using the specified mode."""
        if mode == "keyword":
            return await self._keyword_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
        elif mode == "semantic":
            return await self._semantic_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
        else:
            return await self._hybrid_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )

    async def _keyword_search(
        self,
        query: str,
        mood: str | None,
        tag_ids: list[int] | None,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """FTS5 search with optional filters. Returns results and total count."""
        fts_q = text("""
            SELECT e.id, e.entry_date, e.title,
                   snippet(entries_fts, 1, '<mark>', '</mark>', '...', 20) AS snippet,
                   bm25(entries_fts) AS rank
            FROM entries_fts
            JOIN entries e ON e.id = entries_fts.rowid
            WHERE entries_fts MATCH :query
              AND e.is_deleted = 0
        """)

        params: dict[str, object] = {"query": query}

        conditions = []
        if mood:
            conditions.append("e.mood = :mood")
            params["mood"] = mood
        if date_from:
            conditions.append("e.entry_date >= :date_from")
            params["date_from"] = str(date_from)
        if date_to:
            conditions.append("e.entry_date <= :date_to")
            params["date_to"] = str(date_to)
        if tag_ids:
            placeholders = ", ".join(f":tag_{i}" for i in range(len(tag_ids)))
            conditions.append(
                f"e.id IN (SELECT et.entry_id FROM entry_tags et WHERE et.tag_id IN ({placeholders}))"
            )
            for i, tid in enumerate(tag_ids):
                params[f"tag_{i}"] = tid

        if conditions:
            fts_q = text(str(fts_q) + " AND " + " AND ".join(conditions))

        count_sql = f"SELECT COUNT(*) FROM ({str(fts_q)})"
        total = (await self.db.execute(text(count_sql), params)).scalar_one()

        paginated = text(str(fts_q) + " ORDER BY rank LIMIT :lim OFFSET :off")
        params["lim"] = limit
        params["off"] = offset
        result = await self.db.execute(paginated, params)

        items = [
            SearchResultEntry(
                id=row.id,
                entry_date=row.entry_date,
                title=row.title,
                snippet=row.snippet,
                rank=row.rank,
            )
            for row in result
        ]
        return items, total

    async def _semantic_search(
        self,
        query: str,
        mood: str | None,
        tag_ids: list[int] | None,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Search using embedding cosine similarity.

        Uses **numpy vectorisation** instead of a Python loop: all
        embeddings are loaded into a single 2-D array and cosine similarity
        is computed in one matrix operation. For N embeddings of D dims
        this is O(N×D) in C (BLAS) rather than O(N×D) in interpreted Python
        — typically 50–100× faster for real-world corpus sizes.
        """
        import numpy as np

        from app.services.ollama_service import OllamaService

        try:
            ollama = OllamaService()
            query_vec = await ollama.embed(query)
        except Exception:
            logger.warning("Failed to generate embedding for search query", exc_info=True)
            return [], 0

        # Build filtered query for embeddings
        stmt = (
            select(EntryEmbedding.entry_id, EntryEmbedding.embedding)
            .join(Entry, Entry.id == EntryEmbedding.entry_id)
            .where(~Entry.is_deleted)
        )

        from app.services.entry_service import EntryService
        stmt = EntryService._apply_filters(stmt, tag_ids, mood, None, None)

        if date_from:
            stmt = stmt.where(Entry.entry_date >= date_from)
        if date_to:
            stmt = stmt.where(Entry.entry_date <= date_to)

        result = await self.db.execute(stmt)
        rows = result.fetchall()
        if not rows:
            return [], 0

        # ── Vectorised cosine similarity ──────────────────────────
        entry_ids_raw = [row.entry_id for row in rows]
        # Stack all embeddings into a single (N, D) float32 matrix.
        matrix = np.array(
            [json.loads(row.embedding) for row in rows], dtype=np.float32
        )
        q = np.array(query_vec, dtype=np.float32)

        # Cosine similarity = dot(a,b) / (||a|| * ||b||)
        # Normalise rows and query once, then a single matmul.
        norms = np.linalg.norm(matrix, axis=1)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return [], 0
        # Guard against zero-norm rows.
        safe = norms > 0
        similarities = np.zeros(len(rows), dtype=np.float32)
        similarities[safe] = (matrix[safe] @ q) / (norms[safe] * q_norm)

        # Filter + rank in one pass (threshold > 0.1)
        above = np.where(similarities > 0.1)[0]
        if len(above) == 0:
            return [], 0
        # Sort by score descending
        ranked = above[np.argsort(-similarities[above])]
        total = len(ranked)
        page = ranked[offset : offset + limit]

        if len(page) == 0:
            return [], 0

        # Load entry details for the page
        page_ids = [int(entry_ids_raw[i]) for i in page]
        entries_result = await self.db.execute(select(Entry).where(Entry.id.in_(page_ids)))
        entry_map = {e.id: e for e in entries_result.scalars().all()}

        items = []
        for idx in page:
            eid = int(entry_ids_raw[idx])
            entry = entry_map.get(eid)
            if entry:
                score = float(similarities[idx])
                items.append(
                    SearchResultEntry(
                        id=entry.id,
                        entry_date=entry.entry_date,
                        title=entry.title,
                        snippet=entry.body[:200] + "..." if len(entry.body) > 200 else entry.body,
                        rank=-score,  # Negative because lower rank = better in FTS5
                        similarity_score=round(score, 4),
                    )
                )

        return items, total

    async def _hybrid_search(
        self,
        query: str,
        mood: str | None,
        tag_ids: list[int] | None,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Hybrid search combining FTS5 BM25 and cosine similarity via RRF."""
        # Run sequentially to avoid concurrent access on same AsyncSession
        keyword_result = await self._keyword_search(
            query, mood, tag_ids, date_from, date_to, 0, 100
        )
        semantic_result = await self._semantic_search(
            query, mood, tag_ids, date_from, date_to, 0, 100
        )

        keyword_items, keyword_total = keyword_result
        semantic_items, semantic_total = semantic_result

        # If no semantic results, fall back to keyword-only
        if not semantic_items:
            if keyword_items:
                return keyword_items[offset : offset + limit], len(keyword_items)
            return [], 0

        # If no keyword results, use semantic only
        if not keyword_items:
            return semantic_items[offset : offset + limit], len(semantic_items)

        # Reciprocal Rank Fusion (RRF)
        K = 60  # Standard RRF constant
        rrf_scores: dict[int, float] = {}

        for rank, item in enumerate(keyword_items):
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + 1.0 / (K + rank + 1)

        for rank, item in enumerate(semantic_items):
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + 1.0 / (K + rank + 1)

        # Build merged results
        all_items = {item.id: item for item in keyword_items + semantic_items}
        merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        total = len(merged)
        page = merged[offset : offset + limit]

        items = []
        for entry_id, rrf_score in page:
            found = all_items.get(entry_id)
            if found:
                items.append(
                    SearchResultEntry(
                        id=found.id,
                        entry_date=found.entry_date,
                        title=found.title,
                        snippet=found.snippet,
                        rank=rrf_score,
                        similarity_score=found.similarity_score,
                    )
                )

        return items, total
