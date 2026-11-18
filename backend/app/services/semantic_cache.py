"""In-memory cache of embeddings for fast semantic search.

LifeLogr is a local, single-user app, so holding every non-deleted entry's
embedding in RAM turns each search from an O(N) DB scan + N×``json.loads``
into a candidate-ID query plus a few thousand multiply-adds. Vectors are
stored as **float16** (2 bytes per component — half the RAM of the float32
they arrive as) and scored with a pure-Python dot product: no numpy on this
path, so semantic search carries no numeric-stack dependency of its own.

float16 precision
-----------------
float16 carries ~3 decimal digits, so a quantised row's dot products drift by
~1e-3 from the float64 values the DB stores. Embedding cosine similarities
differ by far more than that between *relevant* and *irrelevant* entries, and
the threshold (default 0.1) sits well clear of the noise floor, so ranking and
cut-off are unaffected (asserted in ``tests/unit/test_semantic_cache.py``).
Rows are normalised in float64 *before* quantisation, so the per-row scale is
exact and only per-component rounding remains.

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
never observe a half-updated vector blob; the synchronous mutators rebuild the
state and swap it under ``self._mutex``, and DB reloads are serialised by the
async ``self._lock``. Previously ``update_entry``/``remove_entry`` mutated the
live arrays and dict in place while ``search`` read them, which could hand a
search a vector set whose row count no longer matched ``_pos``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
import threading
from collections.abc import Callable
from typing import Any, NamedTuple

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

# Little-endian IEEE-754 half precision: the on-RAM (and only) vector storage.
_E_ITEMSIZE = 2

# ``struct.Struct`` compiled per dimension — one per distinct embedding width.
_row_structs: dict[int, struct.Struct] = {}


def _row_struct(dim: int) -> struct.Struct:
    """Compiled ``Struct`` packing/unpacking one float16 row of *dim* components."""
    s = _row_structs.get(dim)
    if s is None:
        s = struct.Struct(f"<{dim}e")
        if len(_row_structs) < 64:  # bounded: dims are few (one per embed model)
            _row_structs[dim] = s
    return s


def _unit(vec: list[float]) -> list[float] | None:
    """L2-normalise in float64, or ``None`` for zero/non-finite vectors."""
    n = math.sqrt(math.fsum(x * x for x in vec))
    if not math.isfinite(n) or n == 0.0:
        return None
    return [x / n for x in vec]


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
    """Immutable snapshot of the cached vectors (float16, row-major)."""

    ids: tuple[int, ...]
    dim: int
    blobs: bytes  # ``dim * _E_ITEMSIZE`` bytes per row, little-endian float16
    pos: dict[int, int]  # entry_id → row index in blobs


def _empty_state() -> _CacheState:
    return _CacheState((), 0, b"", {})


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
        return len(self._state.ids)

    @property
    def dim(self) -> int:
        """Component count of the cached vectors (0 when empty)."""
        return self._state.dim

    @property
    def entry_ids(self) -> tuple[int, ...]:
        """Cached entry ids (the published snapshot — treat as read-only)."""
        return self._state.ids

    @property
    def _pos(self) -> dict[int, int]:
        """entry_id → row index map — treat as read-only."""
        return self._state.pos

    def _row(self, idx: int) -> tuple[float, ...]:
        """Decode row *idx* back to Python floats (tests / debugging)."""
        return _row_struct(self._state.dim).unpack_from(
            self._state.blobs, idx * self._state.dim * _E_ITEMSIZE
        )

    @staticmethod
    def _pack_row(unit: list[float]) -> bytes:
        """Quantise a normalised row to packed float16."""
        return _row_struct(len(unit)).pack(*unit)

    @staticmethod
    def _build_state(rows: list[Any]) -> _CacheState:
        """Normalise DB rows into a cache snapshot.

        Rows for a *different* embed model, unparsable vectors, rows whose
        dimension disagrees with the rest, and zero/non-finite vectors are
        skipped: after an embed-model swap the table holds mixed dimensions,
        and stacking those used to turn *every* semantic/hybrid search into a
        500 until a rebuild happened to fix it.
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
        blobs: list[bytes] = []
        ids: list[int] = []
        for eid, vec in parsed:
            if len(vec) != dim:
                skipped += 1
                continue
            unit = _unit(vec)
            if unit is None:
                skipped += 1
                logger.warning(
                    "SemanticSearchCache skipped embedding %d: zero or non-finite vector", eid
                )
                continue
            blobs.append(SemanticSearchCache._pack_row(unit))
            ids.append(eid)
        if not ids:
            if skipped:
                logger.info("SemanticSearchCache skipped %d mismatched embeddings", skipped)
            return _empty_state()
        if skipped:
            logger.info("SemanticSearchCache skipped %d mismatched embeddings", skipped)

        pos = {eid: i for i, eid in enumerate(ids)}
        logger.info("SemanticSearchCache loaded %d vectors (%d dims, float16)", len(ids), dim)
        return _CacheState(tuple(ids), dim, b"".join(blobs), pos)

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
        if not state.ids or not candidate_ids:
            return []
        positions = [state.pos[eid] for eid in candidate_ids if eid in state.pos]
        if not positions:
            return []
        dim = state.dim
        if len(query_vec) != dim:  # stale-dimension snapshot → let the reload heal it
            return []

        qn = math.sqrt(math.fsum(float(x) * float(x) for x in query_vec))
        if qn == 0.0:
            return []
        q = [float(x) / qn for x in query_vec]  # rows are unit → cosine == dot product

        unpack_row = _row_struct(dim).unpack_from
        row_bytes = dim * _E_ITEMSIZE
        above: list[tuple[float, int]] = []
        for p in positions:
            row = unpack_row(state.blobs, p * row_bytes)
            sim = sum(a * b for a, b in zip(row, q, strict=True))
            if sim > threshold:
                above.append((sim, p))
        if not above:
            return []
        above.sort(key=lambda t: -t[0])  # stable: equal scores keep candidate order
        return [(state.ids[p], sim) for sim, p in above]

    # ── best-effort incremental mutation (ensure_fresh is the backstop) ──

    def update_entry(self, entry_id: int, vec: list[float]) -> None:
        """Add or replace an entry's (normalised, float16) vector in the cache."""
        v = [float(x) for x in vec]
        if not v or not all(math.isfinite(x) for x in v):
            return
        unit = _unit(v)
        if unit is None:  # zero vector matches nothing — don't store it
            return
        with self._mutex:
            state = self._state
            # Dimension change (e.g. embed model swapped) → drop; reload next search.
            if state.ids and state.dim != len(unit):
                self._state = _empty_state()
                return
            row = self._pack_row(unit)
            pos = dict(state.pos)
            ids = state.ids
            blobs = state.blobs
            idx = pos.get(entry_id)
            if idx is None:
                ids = ids + (entry_id,)
                blobs = blobs + row
                idx = len(ids) - 1
            else:
                off = idx * len(row)
                blobs = blobs[:off] + row + blobs[off + len(row) :]
            pos[entry_id] = idx
            self._state = _CacheState(ids, len(unit), blobs, pos)

    def remove_entry(self, entry_id: int) -> None:
        with self._mutex:
            state = self._state
            idx = state.pos.get(entry_id)
            if idx is None or not state.ids:
                return
            row_bytes = state.dim * _E_ITEMSIZE
            ids = state.ids[:idx] + state.ids[idx + 1 :]
            blobs = state.blobs[: idx * row_bytes] + state.blobs[(idx + 1) * row_bytes :]
            if not ids:
                self._state = _empty_state()
                return
            pos = {eid: i for i, eid in enumerate(ids)}
            self._state = _CacheState(ids, state.dim, blobs, pos)

    def reset(self) -> None:
        """Drop everything (forced reload / test isolation)."""
        with self._mutex:
            self._state = _empty_state()


def _maybe_backfill_entries() -> None:
    """Opportunistic backfill of entries that never got an embedding.

    Entries saved while the embed backend was down stay invisible to semantic
    search forever unless something retries, so the (rate-limited) enrichment
    sweep rides the entry-cache search path instead of a scheduler entry.
    Entry-cache only — the note cache passes ``backfill=None``: notes get a
    fresh vector on every save.
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
