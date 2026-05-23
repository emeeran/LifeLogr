"""SearchService — FTS5 full-text search, semantic search, and hybrid search."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.schemas.search import SearchResultEntry, SearchMode
from app.services.enrichment_service import cosine_similarity


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
            return await self._keyword_search(query, mood, tag_ids, date_from, date_to, offset, limit)
        elif mode == "semantic":
            return await self._semantic_search(query, offset, limit)
        else:
            return await self._hybrid_search(query, mood, tag_ids, date_from, date_to, offset, limit)

    async def _keyword_search(
        self, query: str, mood: str | None, tag_ids: list[int] | None,
        date_from: date | None, date_to: date | None, offset: int, limit: int,
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
            conditions.append(f"e.id IN (SELECT et.entry_id FROM entry_tags et WHERE et.tag_id IN ({placeholders}))")
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
        self, query: str, offset: int, limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Search using embedding cosine similarity."""
        from app.services.ollama_service import OllamaService

        try:
            ollama = OllamaService()
            query_vec = await ollama.embed(query)
        except Exception:
            return [], 0

        # Load all embeddings
        result = await self.db.execute(
            select(EntryEmbedding.entry_id, EntryEmbedding.embedding)
        )
        similarities: list[tuple[int, float]] = []
        for row in result:
            vec = json.loads(row.embedding)
            score = cosine_similarity(query_vec, vec)
            similarities.append((row.entry_id, score))

        similarities.sort(key=lambda x: x[1], reverse=True)
        total = len(similarities)
        page = similarities[offset:offset + limit]

        if not page:
            return [], 0

        # Load entry details for the page
        entry_ids = [e[0] for e in page]
        entries_result = await self.db.execute(
            select(Entry).where(Entry.id.in_(entry_ids), ~Entry.is_deleted)
        )
        entry_map = {e.id: e for e in entries_result.scalars().all()}

        items = []
        for entry_id, score in page:
            entry = entry_map.get(entry_id)
            if entry:
                items.append(SearchResultEntry(
                    id=entry.id,
                    entry_date=entry.entry_date,
                    title=entry.title,
                    snippet=entry.body[:200] + "..." if len(entry.body) > 200 else entry.body,
                    rank=-score,  # Negative because lower rank = better in FTS5
                    similarity_score=round(score, 4),
                ))

        return items, total

    async def _hybrid_search(
        self, query: str, mood: str | None, tag_ids: list[int] | None,
        date_from: date | None, date_to: date | None, offset: int, limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Hybrid search combining FTS5 BM25 and cosine similarity via RRF."""
        import asyncio

        # Run both searches in parallel
        keyword_task = asyncio.create_task(
            self._keyword_search(query, mood, tag_ids, date_from, date_to, 0, 100)
        )
        semantic_task = asyncio.create_task(
            self._semantic_search(query, 0, 100)
        )

        gather_results = await asyncio.gather(
            keyword_task, semantic_task, return_exceptions=True
        )

        keyword_result = gather_results[0]
        semantic_result = gather_results[1]

        if isinstance(keyword_result, BaseException):
            keyword_items: list[SearchResultEntry] = []
            keyword_total: int = 0
        else:
            keyword_items, keyword_total = keyword_result

        if isinstance(semantic_result, BaseException):
            semantic_items: list[SearchResultEntry] = []
            semantic_total: int = 0
        else:
            semantic_items, semantic_total = semantic_result

        # If no semantic results, fall back to keyword-only
        if not semantic_items:
            if keyword_items:
                return keyword_items[offset:offset + limit], len(keyword_items)
            return [], 0

        # If no keyword results, use semantic only
        if not keyword_items:
            return semantic_items[offset:offset + limit], len(semantic_items)

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
        page = merged[offset:offset + limit]

        items = []
        for entry_id, rrf_score in page:
            found = all_items.get(entry_id)
            if found:
                items.append(SearchResultEntry(
                    id=found.id,
                    entry_date=found.entry_date,
                    title=found.title,
                    snippet=found.snippet,
                    rank=rrf_score,
                    similarity_score=found.similarity_score,
                ))

        return items, total
