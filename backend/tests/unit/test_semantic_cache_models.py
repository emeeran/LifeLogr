"""SemanticSearchCache — embed-model awareness and concurrent mutation safety.

A model swap leaves ``entry_embeddings`` holding vectors of mixed dimension; the
cache must skip the foreign rows instead of raising (which used to turn every
semantic/hybrid search into a 500), and its mutators must never let a search
observe a half-updated matrix.
"""

import asyncio
import json
from datetime import date

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.services.semantic_cache import SemanticSearchCache


async def _seed(db: AsyncSession, vec: list[float], model: str | None = None) -> int:
    e = Entry(entry_date=date(2026, 1, 1), body="x")
    db.add(e)
    await db.flush()
    db.add(
        EntryEmbedding(
            entry_id=e.id,
            embedding=json.dumps(vec),
            model_name=model or settings.OLLAMA_EMBED_MODEL,
        )
    )
    await db.commit()
    return e.id


class TestModelFiltering:
    async def test_mixed_dimensions_do_not_crash(self, db_session: AsyncSession):
        """A stale-model vector must not break the load (or the search)."""
        old_id = await _seed(db_session, [1.0, 0.0], model="old-embed-model")  # 2-dim
        await _seed(db_session, [1.0, 0.0, 0.0])  # current model, 3-dim
        cache = SemanticSearchCache()
        await cache.ensure_fresh(db_session)  # must not raise
        assert cache.size == 1  # only the current-model row loaded
        assert old_id not in cache._pos

    async def test_search_works_after_model_swap(self, db_session: AsyncSession):
        live_id = await _seed(db_session, [1.0, 0.0, 0.0])
        await _seed(db_session, [0.0, 1.0], model="old-embed-model")
        cache = SemanticSearchCache()
        await cache.ensure_fresh(db_session)
        ranked = await cache.search(db_session, [1.0, 0.0, 0.0], [live_id])
        assert [eid for eid, _ in ranked] == [live_id]

    async def test_all_foreign_model_rows_yield_empty_cache(self, db_session: AsyncSession):
        await _seed(db_session, [1.0, 0.0], model="someone-elses-model")
        cache = SemanticSearchCache()
        await cache.ensure_fresh(db_session)
        assert cache.size == 0
        assert await cache.search(db_session, [1.0, 0.0], [1]) == []

    async def test_unparsable_vector_is_skipped(self, db_session: AsyncSession):
        e = Entry(entry_date=date(2026, 1, 2), body="y")
        db_session.add(e)
        await db_session.flush()
        db_session.add(EntryEmbedding(entry_id=e.id, embedding="not json"))
        await db_session.commit()
        cache = SemanticSearchCache()
        await cache.ensure_fresh(db_session)  # must not raise
        assert cache.size == 0

    async def test_count_check_ignores_foreign_model_rows(self, db_session: AsyncSession):
        """Stale-model rows must not force a reload on every search."""
        cache = SemanticSearchCache()
        await _seed(db_session, [1.0, 0.0, 0.0])
        await cache.ensure_fresh(db_session)
        snapshot = cache.vectors
        await _seed(db_session, [0.0, 1.0], model="old-embed-model")
        await cache.ensure_fresh(db_session)
        # Unchanged identity → no reload happened.
        assert cache.vectors is snapshot


class TestConcurrency:
    async def test_update_while_searching_is_consistent(self, db_session: AsyncSession):
        """A search must never see a matrix/pos pair that disagree."""
        cache = SemanticSearchCache()
        ids = [await _seed(db_session, [1.0, 0.0]) for _ in range(5)]
        await cache.ensure_fresh(db_session)

        errors: list[str] = []

        async def _hammer_queries() -> None:
            for _ in range(200):
                await asyncio.sleep(0)
                try:
                    state_ids = cache.entry_ids
                    if cache.vectors.shape[0] != state_ids.size:
                        errors.append("vectors/ids diverged")
                    await cache.search(db_session, [1.0, 0.0], ids)
                except Exception as exc:  # noqa: BLE001 — the point is "no crash"
                    errors.append(f"{type(exc).__name__}: {exc}")

        async def _hammer_updates() -> None:
            for i in range(200):
                await asyncio.sleep(0)
                cache.update_entry(10_000 + i, [0.5, 0.5])
                if i % 3 == 0:
                    cache.remove_entry(10_000 + i)

        await asyncio.gather(_hammer_queries(), _hammer_updates())
        assert errors == []

    async def test_remove_then_readd_keeps_shape(self):
        cache = SemanticSearchCache()
        cache.update_entry(1, [1.0, 0.0])
        cache.update_entry(2, [0.0, 1.0])
        cache.remove_entry(1)
        cache.update_entry(3, [1.0, 1.0])
        assert cache.vectors.shape == (2, 2)
        assert set(cache._pos) == {2, 3}
        assert cache._pos[3] == 1
        # Rows stay normalised.
        assert pytest.approx(1.0) == float(np.linalg.norm(cache.vectors[1]))

    async def test_update_existing_row_does_not_change_shape(self):
        cache = SemanticSearchCache()
        cache.update_entry(1, [1.0, 0.0])
        before = cache.vectors.copy()
        cache.update_entry(1, [0.0, 1.0])
        assert cache.vectors.shape == before.shape
        assert not np.array_equal(cache.vectors, before)
