"""SearchService — FTS5 full-text search, semantic search, and hybrid search."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.models.note import Note, NoteTag
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
        """Search entries (via the requested mode) and union in keyword-matched notes.

        Notes are keyword-only in v1 (no embeddings). They are appended after
        entries in the merged stream, with windowed pagination so the combined
        page respects ``offset``/``limit`` and ``total`` is the entry+note count.
        """
        if mode == "keyword":
            entry_items, entry_total = await self._keyword_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
        elif mode == "semantic":
            entry_items, entry_total = await self._semantic_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
        else:
            entry_items, entry_total = await self._hybrid_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )

        # Notes occupy stream positions after all entries. Fetch only the slice
        # of notes that falls within the requested [offset, offset+limit) window.
        entries_on_page = len(entry_items)
        note_offset = max(0, offset - entry_total)
        note_limit = max(0, limit - entries_on_page)
        note_items, note_total = await self._notes_keyword_search(
            query, tag_ids, note_offset, note_limit
        )
        return entry_items + note_items, entry_total + note_total

    async def _notes_keyword_search(
        self,
        query: str,
        tag_ids: list[int] | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Keyword search over notes (FTS5 with ILIKE fallback).

        The ILIKE fallback covers the test DB (whose ``notes_fts`` has no sync
        triggers and is therefore empty) and any production moment where the
        FTS index is unavailable.
        """
        # ── FTS5 path ──
        try:
            fts_q = text("""
                SELECT n.id, n.folder_id, n.updated_at, n.title,
                       snippet(notes_fts, 1, '<mark>', '</mark>', '...', 20) AS snippet,
                       bm25(notes_fts) AS rank
                FROM notes_fts
                JOIN notes n ON n.id = notes_fts.rowid
                WHERE notes_fts MATCH :query AND n.is_deleted = 0
            """)
            params: dict[str, object] = {"query": query}
            if tag_ids:
                placeholders = ", ".join(f":tag_{i}" for i in range(len(tag_ids)))
                fts_q = text(
                    str(fts_q)
                    + f" AND n.id IN (SELECT nt.note_id FROM note_tags nt WHERE nt.tag_id IN ({placeholders}))"
                )
                for i, tid in enumerate(tag_ids):
                    params[f"tag_{i}"] = tid
            total = (
                await self.db.execute(text(f"SELECT COUNT(*) FROM ({str(fts_q)})"), params)
            ).scalar_one()
            if total > 0:
                paginated = text(str(fts_q) + " ORDER BY rank LIMIT :lim OFFSET :off")
                params["lim"] = limit
                params["off"] = offset
                rows = (await self.db.execute(paginated, params)).fetchall()
                return [
                    SearchResultEntry(
                        type="note",
                        id=row.id,
                        entry_date=None,
                        folder_id=row.folder_id,
                        updated_at=row.updated_at,
                        title=row.title,
                        snippet=row.snippet,
                        rank=row.rank,
                    )
                    for row in rows
                ], total
        except Exception:
            logger.warning("Note FTS search failed, falling back to ILIKE", exc_info=True)

        # ── ILIKE fallback ──
        pattern = f"%{query}%"
        base = (
            select(Note.id, Note.folder_id, Note.updated_at, Note.title, Note.body)
            .where(
                Note.is_deleted == False,  # noqa: E712
                (Note.title.ilike(pattern)) | (Note.body.ilike(pattern)),
            )
        )
        if tag_ids:
            base = base.where(
                Note.id.in_(select(NoteTag.note_id).where(NoteTag.tag_id.in_(tag_ids)))
            )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self.db.execute(
                base.order_by(Note.updated_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        return [
            SearchResultEntry(
                type="note",
                id=r.id,
                entry_date=None,
                folder_id=r.folder_id,
                updated_at=r.updated_at,
                title=r.title,
                snippet=(r.body[:200] + "..." if len(r.body) > 200 else r.body),
                rank=0.0,
            )
            for r in rows
        ], total

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

        Vectors are served from an in-memory cache (see ``app.services.semantic_cache``);
        the per-query DB work is just the filter-passing candidate IDs — no
        embedding blobs are loaded or JSON-parsed on each search.
        """
        from app.services.ollama_service import OllamaService
        from app.services.semantic_cache import get_semantic_cache

        try:
            query_vec = await OllamaService().embed(query)
        except Exception:
            logger.warning("Failed to generate embedding for search query", exc_info=True)
            return [], 0

        # Candidate entry_ids: the same filters the old embedding query applied,
        # but selecting IDs only — the cache supplies the actual vectors.
        stmt = (
            select(EntryEmbedding.entry_id)
            .join(Entry, Entry.id == EntryEmbedding.entry_id)
            .where(~Entry.is_deleted)
        )
        from app.services.entry_service import EntryService

        stmt = EntryService._apply_filters(stmt, tag_ids, mood, None, None)
        if date_from:
            stmt = stmt.where(Entry.entry_date >= date_from)
        if date_to:
            stmt = stmt.where(Entry.entry_date <= date_to)
        candidate_ids = [int(i) for i in (await self.db.execute(stmt)).scalars().all()]

        ranked = await get_semantic_cache().search(self.db, query_vec, candidate_ids)
        if not ranked:
            return [], 0
        total = len(ranked)
        page = ranked[offset : offset + limit]
        if not page:
            return [], 0

        page_ids = [eid for eid, _ in page]
        entries_result = await self.db.execute(select(Entry).where(Entry.id.in_(page_ids)))
        entry_map = {e.id: e for e in entries_result.scalars().all()}

        items = []
        for eid, score in page:
            entry = entry_map.get(eid)
            if entry:
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
