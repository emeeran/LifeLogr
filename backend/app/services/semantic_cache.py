"""In-memory cache of embeddings for fast semantic search.

LifeLogr is a local, single-user app, so holding a pre-stacked, L2-normalised
float32 matrix of every non-deleted entry's embedding in RAM is cheap and turns
each search from an O(N) DB scan + N×``json.loads`` into a cheap candidate-ID
query plus a single BLAS matmul.

There is one instance per embedded entity kind (entries and notes) —
:func:`get_semantic_cache` and :func:`get_note_semantic_cache`. Both store the
same embed model's vectors (one vector space); only the source table and the
"live" join differ. The notes below describe the mechanics shared by both.

Correctness model
-----------------
The cache mirrors the universe ``_semantic_search`` used to load every call:
every embedding whose entry is **not** soft-deleted *and* whose ``model_name``
matches the currently configured embed model. Two mechanisms keep it in sync
with the database, in escalating order of trust:

1. ``update_entry`` / ``remove_entry`` — best-effort incremental updates called
   from the embedding writer (enrichment) and entry soft-delete. Fast, but only
   as reliable as the call sites.
2. ``ensure_fresh`` — a per-search **count check** (the correctness backstop).
   If the live row count for the current model diverges from the cache — delete,
   restore, hard-delete, bulk SQL, a model swap, or any hook we missed — the
   cache reloads itself before answering.

(2) is what makes missed hooks self-heal instead of silently corrupting results.
Encrypted entries keep their embeddings, so encryption needs no hook here; the
cache simply includes them, matching the live query's ``~is_deleted`` filter.

Concurrency model
-----------------
The cache state is an immutable snapshot (``_CacheState``) published by a single
attribute assignment. Readers grab one snapshot and work on it, so a search can
never observe a half-updated matrix; the synchronous mutators rebuild the state
and swap it under ``self._mutex``, and DB reloads are serialised by the async
``self._lock``. Previously ``update_entry``/``remove_entry`` mutated the live
arrays and dict in place while ``search`` read them, which could hand a search a
matrix whose row count no longer matched ``_pos``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from typing import Any, NamedTuple

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select

from app.core.config import settings
from app.models.embedding import EntryEmbedding, NoteEmbedding
from app.models.entry import Entry
from app.models.note import Note

logger = logging.getLogger(__name__)

# ``(id, embedding_json, model_name)`` rows of one entity kind's live vectors.
_LiveRowsStmt = Callable[[], Select[tuple[int, str, str]]]
_LiveCountStmt = Callable[[], Select[tuple[int]]]


def _live_embeddings_stmt() -> Select[tuple[int, str, str]]:
    """Live (non-deleted) embeddings — the universe the cache mirrors.

    ``model_name`` is selected so the loader can drop vectors produced by a
    previous embed model instead of stacking mismatched dimensions.
    """
    return (
        select(EntryEmbedding.entry_id, EntryEmbedding.embedding, EntryEmbedding.model_name)
        .join(Entry, Entry.id == EntryEmbedding.entry_id)
        .where(~Entry.is_deleted)
    )


def _live_embedding_count_stmt() -> Select[tuple[int]]:
    """Count of live embeddings **for the current embed model**.

    Filtering by model here (not just ``~is_deleted``) matters: after a model
    swap the stale rows would otherwise keep the count permanently out of sync
    with the (model-filtered) cache, forcing a pointless reload on every search.
    """
    return (
        select(func.count())
        .select_from(EntryEmbedding)
        .join(Entry, Entry.id == EntryEmbedding.entry_id)
        .where(~Entry.is_deleted, EntryEmbedding.model_name == settings.OLLAMA_EMBED_MODEL)
    )


def _live_note_embeddings_stmt() -> Select[tuple[int, str, str]]:
    """Note flavour of :func:`_live_embeddings_stmt` (see it for the contract)."""
    return (
        select(NoteEmbedding.note_id, NoteEmbedding.embedding, NoteEmbedding.model_name)
        .join(Note, Note.id == NoteEmbedding.note_id)
        .where(~Note.is_deleted)
    )


def _live_note_embedding_count_stmt() -> Select[tuple[int]]:
    """Note flavour of :func:`_live_embedding_count_stmt` (see it for the contract)."""
    return (
        select(func.count())
        .select_from(NoteEmbedding)
        .join(Note, Note.id == NoteEmbedding.note_id)
        .where(~Note.is_deleted, NoteEmbedding.model_name == settings.OLLAMA_EMBED_MODEL)
    )


class _CacheState(NamedTuple):
    """Immutable snapshot of the cached vectors."""

    ids: np.ndarray
    vectors: np.ndarray
    pos: dict[int, int]  # entry_id → row index in vectors


def _empty_state() -> _CacheState:
    return _CacheState(
        np.empty(0, dtype=np.int32), np.empty((0, 0), dtype=np.float32), {}
    )


class SemanticSearchCache:
    """Process-wide cache: ``entity_id → L2-normalised embedding`` for live rows.

    One instance per embedded entity kind: the default (no-argument) constructor
    mirrors **entries**, which is what every pre-existing call site and test
    gets; the note universe is injected via ``live_rows``/``live_count`` (see
    :func:`get_note_semantic_cache`). ``update_entry``/``remove_entry`` keep
    their entry-named API — the ids they take are simply "ids of whatever kind
    this instance mirrors", and the two caches are never mixed (entries and
    notes have overlapping integer id spaces, which is exactly why they can't
    share one cache).
    """

    def __init__(
        self,
        *,
        live_rows: _LiveRowsStmt | None = None,
        live_count: _LiveCountStmt | None = None,
        backfill: Callable[[], None] | None = None,
    ) -> None:
        self._live_rows = live_rows or _live_embeddings_stmt
        self._live_count = live_count or _live_embedding_count_stmt
        self._backfill = backfill if backfill is not None else _maybe_backfill_entries
        # Serialises DB reloads (async context).
        self._lock = asyncio.Lock()
        # Serialises snapshot swaps for the synchronous mutators, which are
        # called from running event loops but never await.
        self._mutex = threading.Lock()
        self._state = _empty_state()

    @property
    def size(self) -> int:
        return int(self._state.ids.size)

    @property
    def entry_ids(self) -> np.ndarray:
        """Cached entry ids (the published snapshot — treat as read-only)."""
        return self._state.ids

    @property
    def vectors(self) -> np.ndarray:
        """Cached (normalised) vector matrix — treat as read-only."""
        return self._state.vectors

    @property
    def _pos(self) -> dict[int, int]:
        """entry_id → row index map — treat as read-only."""
        return self._state.pos

    @staticmethod
    def _build_state(rows: list[Any]) -> _CacheState:
        """Normalise DB rows into a cache snapshot.

        Rows for a *different* embed model, unparsable vectors, and rows whose
        dimension disagrees with the rest are skipped: after an embed-model swap
        the table holds mixed dimensions, and stacking those raises — which used
        to turn *every* semantic/hybrid search into a 500 until a rebuild
        happened to fix it.
        """
        model = settings.OLLAMA_EMBED_MODEL
        parsed: list[tuple[int, list[float]]] = []
        skipped = 0
        for r in rows:
            if r.model_name != model:
                skipped += 1
                continue
            try:
                vec = json.loads(r.embedding)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(vec, list) or not vec:
                skipped += 1
                continue
            parsed.append((int(r.entry_id), [float(x) for x in vec]))

        if not parsed:
            if skipped:
                logger.info(
                    "SemanticSearchCache skipped %d embeddings (other/unreadable model)", skipped
                )
            return _empty_state()

        dim = len(parsed[0][1])
        kept = [(eid, vec) for eid, vec in parsed if len(vec) == dim]
        skipped += len(parsed) - len(kept)
        if not kept:
            return _empty_state()
        if skipped:
            logger.info("SemanticSearchCache skipped %d mismatched embeddings", skipped)

        ids = np.array([eid for eid, _ in kept], dtype=np.int32)
        matrix = np.array([vec for _, vec in kept], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # guard zero-norm rows
        pos = {int(eid): i for i, eid in enumerate(ids)}
        logger.info("SemanticSearchCache loaded %d vectors (%d dims)", len(kept), dim)
        return _CacheState(ids, matrix / norms, pos)

    async def _load(self, db: AsyncSession) -> None:
        rows = (await db.execute(self._live_rows())).fetchall()
        state = self._build_state(list(rows))
        with self._mutex:
            self._state = state

    async def ensure_fresh(self, db: AsyncSession) -> None:
        """Reload if empty or if the live embedding count has diverged.

        The count check is the correctness backstop: any path that changes which
        embeddings are live (delete/restore/bulk SQL/a missed hook) changes the
        count and forces a reload. Same-count content edits are handled by
        ``update_entry``.
        """
        live = (await db.execute(self._live_count())).scalar_one()
        if self.size != live:
            async with self._lock:
                # Re-check under the lock — a concurrent search may have reloaded.
                live = (await db.execute(self._live_count())).scalar_one()
                if self.size != live:
                    await self._load(db)
        if self._backfill is not None:
            self._backfill()

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
        state = self._state  # one immutable snapshot for the whole read
        if state.ids.size == 0 or not candidate_ids:
            return []
        positions = [state.pos[eid] for eid in candidate_ids if eid in state.pos]
        if not positions:
            return []
        idx = np.asarray(positions, dtype=np.int64)
        sub = state.vectors[idx]  # rows already normalised → cosine == dot product
        sub_ids = state.ids[idx]

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
        with self._mutex:
            state = self._state
            # Dimension change (e.g. embed model swapped) → drop; reload next search.
            if state.vectors.ndim == 2 and state.vectors.shape[1] not in (0, v.shape[0]):
                self._state = _empty_state()
                return
            if entry_id in state.pos:
                matrix = state.vectors.copy()
                matrix[state.pos[entry_id]] = v
                self._state = _CacheState(state.ids, matrix, dict(state.pos))
                return
            ids = np.append(state.ids, np.int32(entry_id)).astype(np.int32, copy=False)
            matrix = v.reshape(1, -1) if state.vectors.size == 0 else np.vstack([state.vectors, v])
            pos = dict(state.pos)
            pos[entry_id] = int(ids.size) - 1
            self._state = _CacheState(ids, matrix, pos)

    def remove_entry(self, entry_id: int) -> None:
        with self._mutex:
            state = self._state
            idx = state.pos.get(entry_id)
            if idx is None or state.vectors.ndim != 2 or state.vectors.shape[0] == 0:
                return
            ids = np.delete(state.ids, idx).astype(np.int32, copy=False)
            matrix = np.delete(state.vectors, idx, axis=0)
            pos = {int(eid): i for i, eid in enumerate(ids)}
            self._state = _CacheState(ids, matrix, pos)

    def reset(self) -> None:
        """Drop everything (forced reload / test isolation)."""
        with self._mutex:
            self._state = _empty_state()


def _maybe_backfill_entries() -> None:
    """Opportunistic backfill of entries that never got an embedding.

    Entries saved while the embed backend was down stay invisible to
    semantic search forever unless something retries. This hooks the
    (rate-limited) enrichment sweep onto the entry-cache search path so the
    backlog drains without a dedicated scheduler entry. Detached +
    error-swallowing; the guard itself is a monotonic timestamp check.

    Entry-cache only (the note cache passes ``backfill=None``) — the sweep is
    written against the entry tables, and notes get a fresh vector on every
    save, so they don't need a sweep yet.
    """
    try:
        from app.services.enrichment_service import maybe_schedule_backfill

        maybe_schedule_backfill()
    except Exception:
        logger.debug("Embedding backfill scheduling failed", exc_info=True)


# Process-wide singletons (local single-user app) — one per embedded kind.
_semantic_cache = SemanticSearchCache()
_note_semantic_cache = SemanticSearchCache(
    live_rows=_live_note_embeddings_stmt,
    live_count=_live_note_embedding_count_stmt,
    backfill=None,
)


def get_semantic_cache() -> SemanticSearchCache:
    """Entry vector cache (ids are ``entries.id``)."""
    return _semantic_cache


def get_note_semantic_cache() -> SemanticSearchCache:
    """Note vector cache (ids are ``notes.id``).

    Kept separate from :func:`get_semantic_cache` because entries and notes
    share an integer id space — a single cache would silently serve an entry
    vector for a note id.
    """
    return _note_semantic_cache
