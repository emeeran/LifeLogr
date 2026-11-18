"""SearchService — FTS5 full-text search, semantic search, and hybrid search.

Both embedded kinds (entries and notes) participate in every mode: keyword
matches come from their FTS5 indexes, semantic matches from their vector
tables (same embed model ⇒ one shared vector space), and hybrid mode fuses
keyword + semantic per kind with RRF. ``SearchResultEntry.type`` says which
kind a hit is; entries and notes do *not* share an id space, so fusion keys
are ``(type, id)`` pairs.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fts import sanitize_fts_query
from app.models.embedding import EntryEmbedding, NoteEmbedding
from app.models.entry import Entry
from app.models.note import Note, NoteTag
from app.models.reminder import Reminder
from app.schemas.search import SearchMode, SearchResultEntry

logger = logging.getLogger(__name__)

# How deep each mode's sub-search pages before fusion. Bounds the RRF work;
# the sub-totals are the true, uncapped match counts.
_FUSION_WINDOW = 100


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
        """Search entries *and* notes with the requested mode.

        Keyword and semantic modes keep the stream layout "entries, then
        notes": each kind is ranked on its own and the notes that fall inside
        the requested ``[offset, offset+limit)`` window are appended, so
        ``total`` is the entry+note count and no page mixes orderings from two
        different rankers. Hybrid mode instead fuses all four sub-searches
        (entry/note × keyword/semantic) into one ranking, so a note can
        legitimately outrank an entry there.

        Reminders (the "schedule") are keyword-only and date-less — they trail
        the stream in keyword and hybrid modes and are skipped in semantic mode,
        which has no meaningful similarity signal for them.
        """
        if mode == "semantic":
            entry_items, entry_total = await self._semantic_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
            note_items, note_total = await self._notes_semantic_search(
                query, tag_ids, max(0, offset - entry_total), max(0, limit - len(entry_items))
            )
            return entry_items + note_items, entry_total + note_total

        if mode == "hybrid":
            fused_items, fused_total = await self._hybrid_search(
                query, mood, tag_ids, date_from, date_to, offset, limit
            )
            # Reminders occupy stream positions after the fused entry+note page.
            reminder_offset = max(0, offset - fused_total)
            reminder_limit = max(0, limit - len(fused_items))
            reminder_items, reminder_total = await self._reminders_keyword_search(
                query, reminder_offset, reminder_limit
            )
            return fused_items + reminder_items, fused_total + reminder_total

        entry_items, entry_total = await self._keyword_search(
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

        # Reminders (the "schedule") occupy stream positions after entries +
        # notes. Recurring reminders have no single date, so they are keyword-only
        # and date-less (callers read ``updated_at``).
        on_page = entries_on_page + len(note_items)
        reminder_offset = max(0, offset - entry_total - note_total)
        reminder_limit = max(0, limit - on_page)
        reminder_items, reminder_total = await self._reminders_keyword_search(
            query, reminder_offset, reminder_limit
        )
        return (
            entry_items + note_items + reminder_items,
            entry_total + note_total + reminder_total,
        )

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
            params: dict[str, object] = {"query": sanitize_fts_query(query)}
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
        base = select(Note.id, Note.folder_id, Note.updated_at, Note.title, Note.body).where(
            Note.is_deleted == False,  # noqa: E712
            (Note.title.ilike(pattern)) | (Note.body.ilike(pattern)),
        )
        if tag_ids:
            base = base.where(
                Note.id.in_(select(NoteTag.note_id).where(NoteTag.tag_id.in_(tag_ids)))
            )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self.db.execute(base.order_by(Note.updated_at.desc()).offset(offset).limit(limit))
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

    async def _reminders_keyword_search(
        self,
        query: str,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Keyword search over scheduled reminders (ILIKE on title + message).

        Only active reminders are considered. Reminders are recurring and have
        no single date, so ``entry_date`` is left null (callers read
        ``updated_at``).
        """
        pattern = f"%{query}%"
        base = select(Reminder.id, Reminder.title, Reminder.message, Reminder.updated_at).where(
            Reminder.is_active == True,  # noqa: E712
            (Reminder.title.ilike(pattern)) | (Reminder.message.ilike(pattern)),
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        if total == 0 or limit <= 0:
            return [], total
        rows = (
            await self.db.execute(
                base.order_by(Reminder.updated_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        items = [
            SearchResultEntry(
                type="reminder",
                id=r.id,
                entry_date=None,
                updated_at=r.updated_at,
                title=r.title,
                snippet=(r.message.strip() if r.message else "Scheduled reminder"),
                rank=0.0,
            )
            for r in rows
        ]
        return items, total

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

        params: dict[str, object] = {"query": sanitize_fts_query(query)}

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

    async def _notes_semantic_search(
        self,
        query: str,
        tag_ids: list[int] | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchResultEntry], int]:
        """Semantic (cosine-similarity) search over notes.

        Mirrors :meth:`_semantic_search` but reads ``note_embeddings`` via the
        note vector cache. Encrypted notes are excluded from the candidate set
        as well: they never get a vector (encryption drops it), and excluding
        them here keeps a stale pre-encryption row from ever resurfacing.
        """
        from app.services.ollama_service import OllamaService
        from app.services.semantic_cache import get_note_semantic_cache

        try:
            query_vec = await OllamaService().embed(query)
        except Exception:
            logger.warning("Failed to generate embedding for search query", exc_info=True)
            return [], 0

        # Candidate note_ids — the cache supplies the actual vectors.
        stmt = (
            select(NoteEmbedding.note_id)
            .join(Note, Note.id == NoteEmbedding.note_id)
            .where(~Note.is_deleted, ~Note.is_encrypted)
        )
        if tag_ids:
            stmt = stmt.where(Note.id.in_(select(NoteTag.note_id).where(NoteTag.tag_id.in_(tag_ids))))
        candidate_ids = [int(i) for i in (await self.db.execute(stmt)).scalars().all()]

        ranked = await get_note_semantic_cache().search(self.db, query_vec, candidate_ids)
        if not ranked:
            return [], 0
        total = len(ranked)
        page = ranked[offset : offset + limit]
        if not page:
            return [], 0

        page_ids = [nid for nid, _ in page]
        rows = await self.db.execute(
            select(Note.id, Note.folder_id, Note.updated_at, Note.title, Note.body).where(
                Note.id.in_(page_ids)
            )
        )
        note_map = {r.id: r for r in rows.fetchall()}

        items = []
        for nid, score in page:
            row = note_map.get(nid)
            if row is not None:
                items.append(
                    SearchResultEntry(
                        type="note",
                        id=row.id,
                        folder_id=row.folder_id,
                        updated_at=row.updated_at,
                        title=row.title,
                        snippet=row.body[:200] + "..." if len(row.body) > 200 else row.body,
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
        """Hybrid search: FTS5 BM25 + cosine similarity fused with RRF.

        All four sub-searches (entries and notes, each keyword + semantic) feed
        one Reciprocal-Rank-Fusion pass keyed by ``(type, id)`` — entries and
        notes have overlapping integer ids, so the key must carry the kind.
        A stream that comes back empty simply contributes nothing, which makes
        the old "fall back to keyword-only / semantic-only" branches fall out
        of the fusion arithmetic.
        """
        # Run sequentially to avoid concurrent access on same AsyncSession. The
        # windowed sub-search pages bound the fusion work; their ``total`` values
        # are the true, uncapped match counts and are what we report.
        keyword_items, keyword_total = await self._keyword_search(
            query, mood, tag_ids, date_from, date_to, 0, _FUSION_WINDOW
        )
        semantic_items, semantic_total = await self._semantic_search(
            query, mood, tag_ids, date_from, date_to, 0, _FUSION_WINDOW
        )
        note_keyword_items, note_keyword_total = await self._notes_keyword_search(
            query, tag_ids, 0, _FUSION_WINDOW
        )
        note_semantic_items, note_semantic_total = await self._notes_semantic_search(
            query, tag_ids, 0, _FUSION_WINDOW
        )

        # Reciprocal Rank Fusion (RRF)
        K = 60  # Standard RRF constant
        streams = (
            keyword_items,
            semantic_items,
            note_keyword_items,
            note_semantic_items,
        )
        rrf_scores: dict[tuple[str, int], float] = {}
        for stream in streams:
            for rank, item in enumerate(stream):
                # Entries and notes share an id space → the kind is part of the key.
                key: tuple[str, int] = (item.type, item.id)
                rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (K + rank + 1)

        # Build merged results
        all_items: dict[tuple[str, int], SearchResultEntry] = {
            (item.type, item.id): item for stream in streams for item in stream
        }
        merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        # Union of each kind's result sets. ``len(merged)`` is capped at
        # 4 × _FUSION_WINDOW, so it under-reports exactly when a query matches
        # more than the sub-search pages hold; the sub-totals are uncapped, so
        # each union is keyword + semantic − overlap (overlap measured on the
        # fetched pages).
        overlap = len({i.id for i in keyword_items} & {i.id for i in semantic_items})
        note_overlap = len({i.id for i in note_keyword_items} & {i.id for i in note_semantic_items})
        total = (
            keyword_total
            + semantic_total
            - overlap
            + note_keyword_total
            + note_semantic_total
            - note_overlap
        )
        page = merged[offset : offset + limit]

        items = []
        for key, rrf_score in page:
            found = all_items.get(key)
            if found:
                items.append(
                    SearchResultEntry(
                        type=found.type,
                        id=found.id,
                        entry_date=found.entry_date,
                        folder_id=found.folder_id,
                        updated_at=found.updated_at,
                        title=found.title,
                        snippet=found.snippet,
                        rank=rrf_score,
                        similarity_score=found.similarity_score,
                    )
                )

        return items, total
