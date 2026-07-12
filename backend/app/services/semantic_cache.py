"""In-memory cache of entry embeddings for fast semantic search.

LifeLogr is a local, single-user app, so holding a pre-stacked, L2-normalised
float32 matrix of every non-deleted entry's embedding in RAM is cheap and turns
each search from an O(N) DB scan + N×``json.loads`` into a cheap candidate-ID
query plus a single BLAS matmul.

Correctness model
-----------------
The cache mirrors the universe ``_semantic_search`` used to load every call:
every embedding whose entry is **not** soft-deleted. Two mechanisms keep it in
sync with the database, in escalating order of trust:

1. ``update_entry`` / ``remove_entry`` — best-effort incremental updates called
   from the embedding writer (enrichment) and entry soft-delete. Fast, but only
   as reliable as the call sites.
2. ``ensure_fresh`` — a per-search **count check** (the correctness backstop).
   If the live row count diverges from the cache — delete, restore, hard-delete,
   bulk SQL, or any hook we missed — the cache reloads itself before answering.

(2) is what makes missed hooks self-heal instead of silently corrupting results.
Encrypted entries keep their embeddings, so encryption needs no hook here; the
cache simply includes them, matching the live query's ``~is_deleted`` filter.
"""

from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry

logger = logging.getLogger(__name__)


def _live_embeddings_stmt():
    """Live (non-deleted) embeddings — the universe the cache mirrors."""
    return (
        select(EntryEmbedding.entry_id, EntryEmbedding.embedding)
        .join(Entry, Entry.id == EntryEmbedding.entry_id)
        .where(~Entry.is_deleted)
    )


def _live_embedding_count_stmt():
    return (
        select(func.count())
        .select_from(EntryEmbedding)
        .join(Entry, Entry.id == EntryEmbedding.entry_id)
        .where(~Entry.is_deleted)
    )


class SemanticSearchCache:
    """Process-wide cache: ``entry_id → L2-normalised embedding`` for live entries."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.entry_ids: np.ndarray = np.empty(0, dtype=np.int32)
        self.vectors: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self._pos: dict[int, int] = {}  # entry_id → row index in self.vectors

    @property
    def size(self) -> int:
        return int(self.entry_ids.size)

    async def _load(self, db: AsyncSession) -> None:
        rows = (await db.execute(_live_embeddings_stmt())).fetchall()
        if not rows:
            self.entry_ids = np.empty(0, dtype=np.int32)
            self.vectors = np.empty((0, 0), dtype=np.float32)
            self._pos = {}
            return
        ids = np.array([r.entry_id for r in rows], dtype=np.int32)
        matrix = np.array([json.loads(r.embedding) for r in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # guard zero-norm rows
        self.entry_ids = ids
        self.vectors = matrix / norms
        self._pos = {int(eid): i for i, eid in enumerate(ids)}
        logger.info("SemanticSearchCache loaded %d vectors (%d dims)", self.size, self.vectors.shape[1])

    async def ensure_fresh(self, db: AsyncSession) -> None:
        """Reload if empty or if the live embedding count has diverged.

        The count check is the correctness backstop: any path that changes which
        embeddings are live (delete/restore/bulk SQL/a missed hook) changes the
        count and forces a reload. Same-count content edits are handled by
        ``update_entry``.
        """
        live = (await db.execute(_live_embedding_count_stmt())).scalar_one()
        if self.size == live:
            return
        async with self._lock:
            # Re-check under the lock — a concurrent search may have reloaded.
            live = (await db.execute(_live_embedding_count_stmt())).scalar_one()
            if self.size != live:
                await self._load(db)

    async def search(
        self,
        db: AsyncSession,
        query_vec: list[float],
        candidate_ids: list[int],
        threshold: float = 0.1,
    ) -> list[tuple[int, float]]:
        """Return ``(entry_id, score)`` for every candidate above *threshold*,
        ranked by cosine similarity descending.

        ``candidate_ids`` is the filter-passing subset (mood/tags/dates already
        applied by the caller); the cache supplies the vectors so no embedding
        blob is touched per search.
        """
        await self.ensure_fresh(db)
        if self.size == 0 or not candidate_ids:
            return []
        positions = [self._pos[eid] for eid in candidate_ids if eid in self._pos]
        if not positions:
            return []
        idx = np.asarray(positions, dtype=np.int64)
        sub = self.vectors[idx]  # rows already normalised → cosine == dot product
        sub_ids = self.entry_ids[idx]

        q = np.asarray(query_vec, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0:
            return []
        sims = sub @ (q / qn)

        above = np.where(sims > threshold)[0]
        if above.size == 0:
            return []
        order = above[np.argsort(-sims[above])]
        return [(int(sub_ids[i]), float(sims[i])) for i in order]

    # ── best-effort incremental mutation (ensure_fresh is the backstop) ──

    def update_entry(self, entry_id: int, vec: list[float]) -> None:
        """Add or replace an entry's (normalised) vector in the cache."""
        v = np.asarray(vec, dtype=np.float32)
        if v.ndim != 1 or v.size == 0:
            return
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        # Dimension change (e.g. embed model swapped) → drop; reload next search.
        if self.vectors.ndim == 2 and self.vectors.shape[1] not in (0, v.shape[0]):
            self.reset()
            return
        if entry_id in self._pos:
            self.vectors[self._pos[entry_id]] = v
        elif self.vectors.size == 0:
            self.entry_ids = np.array([entry_id], dtype=np.int32)
            self.vectors = v.reshape(1, -1)
            self._pos[entry_id] = 0
        else:
            self.entry_ids = np.append(self.entry_ids, np.int32(entry_id))
            self.vectors = np.vstack([self.vectors, v])
            self._pos[entry_id] = int(self.entry_ids.size) - 1

    def remove_entry(self, entry_id: int) -> None:
        idx = self._pos.pop(entry_id, None)
        if idx is None or self.vectors.ndim != 2 or self.vectors.shape[0] == 0:
            return
        self.entry_ids = np.delete(self.entry_ids, idx)
        self.vectors = np.delete(self.vectors, idx, axis=0)
        self._pos = {int(eid): i for i, eid in enumerate(self.entry_ids)}

    def reset(self) -> None:
        """Drop everything (forced reload / test isolation)."""
        self.entry_ids = np.empty(0, dtype=np.int32)
        self.vectors = np.empty((0, 0), dtype=np.float32)
        self._pos = {}


# Process-wide singleton (local single-user app).
_semantic_cache = SemanticSearchCache()


def get_semantic_cache() -> SemanticSearchCache:
    return _semantic_cache
