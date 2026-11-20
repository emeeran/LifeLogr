"""SemanticSearchCache — load, incremental mutation, self-healing, and ranking."""

import json
import math
import random
import struct
from datetime import date

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.services.semantic_cache import SemanticSearchCache


async def _seed(db: AsyncSession, d: date, vec: list[float]) -> int:
    e = Entry(entry_date=d, body="x")
    db.add(e)
    await db.flush()
    db.add(EntryEmbedding(entry_id=e.id, embedding=json.dumps(vec)))
    await db.commit()
    return e.id


class TestSemanticCacheMutations:
    """Pure in-memory mutation logic (no DB reload involved)."""

    def test_update_entry_adds(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [1.0, 0.0])
        assert 1 in c._pos
        assert c.size == 1

    def test_update_entry_replaces_not_appends(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [1.0, 0.0])
        c.update_entry(1, [0.0, 1.0])
        assert c.size == 1
        assert (c.size, c.dim) == (1, 2)

    def test_remove_entry_reindexes(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [1.0, 0.0])
        c.update_entry(2, [0.0, 1.0])
        c.remove_entry(1)
        assert 1 not in c._pos
        assert c.size == 1
        assert 2 in c._pos  # still tracked after the row shift

    def test_dimension_change_resets(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [1.0, 0.0])  # 2-dim
        c.update_entry(2, [1.0, 0.0, 0.0])  # 3-dim → stale; drop for full reload
        assert c.size == 0


class TestSemanticCacheDbSync:
    async def test_ensure_fresh_loads_from_db(self, db_session: AsyncSession) -> None:
        c = SemanticSearchCache()
        await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])
        await _seed(db_session, date(2026, 1, 2), [0.0, 1.0])
        await c.ensure_fresh(db_session)
        assert c.size == 2

    async def test_reloads_on_out_of_band_count_change(self, db_session: AsyncSession) -> None:
        """A DB write the cache never saw (restore / bulk SQL / missed hook)
        changes the live count and is picked up by the next ensure_fresh."""
        c = SemanticSearchCache()
        await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])
        await c.ensure_fresh(db_session)
        assert c.size == 1
        await _seed(db_session, date(2026, 1, 2), [0.0, 1.0])  # cache unaware
        await c.ensure_fresh(db_session)
        assert c.size == 2  # self-healed

    async def test_soft_delete_drops_via_count_check(self, db_session: AsyncSession) -> None:
        c = SemanticSearchCache()
        eid1 = await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])
        await _seed(db_session, date(2026, 1, 2), [0.0, 1.0])
        await c.ensure_fresh(db_session)
        assert c.size == 2
        # Soft-delete: embedding row stays, but ~is_deleted now excludes it.
        await db_session.execute(
            Entry.__table__.update().where(Entry.id == eid1).values(is_deleted=True)
        )
        await db_session.commit()
        await c.ensure_fresh(db_session)
        assert c.size == 1
        assert eid1 not in c._pos


class TestSemanticCacheSearch:
    async def test_ranks_above_threshold_and_respects_candidates(
        self, db_session: AsyncSession
    ) -> None:
        c = SemanticSearchCache()
        e1 = await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])  # cos=1.0
        e2 = await _seed(db_session, date(2026, 1, 2), [0.9, 0.1])  # cos≈0.99
        e3 = await _seed(db_session, date(2026, 1, 3), [0.0, 1.0])  # cos=0 → dropped
        await c.ensure_fresh(db_session)

        ranked = await c.search(db_session, [1.0, 0.0], [e1, e2, e3])
        ids = [eid for eid, _ in ranked]
        assert e3 not in ids  # below 0.1 threshold
        assert ids[0] == e1  # highest similarity first

        # Candidate filter excludes e1 even though it's the best match.
        ranked = await c.search(db_session, [1.0, 0.0], [e2, e3])
        assert [eid for eid, _ in ranked] == [e2]

    async def test_handles_empty_and_zero_query(self, db_session: AsyncSession) -> None:
        c = SemanticSearchCache()
        eid = await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])
        await c.ensure_fresh(db_session)
        assert await c.search(db_session, [1.0, 0.0], []) == []
        assert await c.search(db_session, [0.0, 0.0], [eid]) == []  # zero query vec

    async def test_dim_mismatched_query_yields_empty(self, db_session: AsyncSession) -> None:
        """A query whose width disagrees with the snapshot answers nothing
        instead of raising; the count check keeps the snapshot itself honest."""
        c = SemanticSearchCache()
        eid = await _seed(db_session, date(2026, 1, 1), [1.0, 0.0])
        await c.ensure_fresh(db_session)
        assert await c.search(db_session, [1.0, 0.0, 0.0], [eid]) == []


class TestFloat16Storage:
    def test_rows_are_packed_float16(self) -> None:
        """Storage is 2 bytes per component — half the float32 the DB holds."""
        c = SemanticSearchCache()
        c.update_entry(1, [0.3, 0.4])
        c.update_entry(2, [0.0, 1.0])
        assert len(c._state.blobs) == c.size * c.dim * 2
        # Quantised round-trip: values come back at float16 precision.
        assert c._row(0) == (
            struct.unpack("<e", struct.pack("<e", 0.6))[0],
            struct.unpack("<e", struct.pack("<e", 0.8))[0],
        )

    def test_zero_and_non_finite_vectors_are_not_stored(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [0.0, 0.0])
        c.update_entry(2, [float("nan"), 1.0])
        c.update_entry(3, [float("inf"), 0.0])
        assert c.size == 0

    def test_float16_rounding_preserves_normalisation(self) -> None:
        c = SemanticSearchCache()
        c.update_entry(1, [3.0, 4.0])
        norm = math.sqrt(sum(x * x for x in c._row(0)))
        assert norm == pytest.approx(1.0, abs=1e-3)


class TestTopKParity:
    """float16 quantisation must not reorder results vs the legacy float32 math.

    The fixture is "many documents at controlled, well-separated relevance":
    each document sits at a distinct angle to the query (similarity spread over
    ~[0.2, 0.98]), with an assertion that the smallest adjacent gap exceeds the
    float16 noise floor — so any reordering the cache does would be a real
    quantisation bug, not two documents tying at 1e-5 apart (which float32
    itself cannot meaningfully order).
    """

    async def test_top_k_matches_float32_reference(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rng = random.Random(42)
        dim, n_docs = 128, 60

        # Random unit query, then an orthonormal complement to build docs in.
        query = [rng.gauss(0.0, 1.0) for _ in range(dim)]
        qn = math.sqrt(sum(x * x for x in query))
        query = [x / qn for x in query]
        basis: list[list[float]] = []
        while len(basis) < 3:
            u = [rng.gauss(0.0, 1.0) for _ in range(dim)]
            for b in [*basis, query]:
                dot = sum(x * y for x, y in zip(u, b, strict=True))
                u = [x - dot * y for x, y in zip(u, b, strict=True)]
            un = math.sqrt(sum(x * x for x in u))
            if un > 1e-6:
                basis.append([x / un for x in u])

        # Evenly spaced angles → similarities spread wide; per-doc jitter stays
        # far smaller than the spacing so adjacent gaps stay decisive.
        angles = [0.20 + i * (1.15 / n_docs) for i in range(n_docs)]
        vecs: list[list[float]] = []
        for theta in angles:
            t = theta + rng.uniform(-0.004, 0.004)
            noise = [rng.gauss(0.0, 1.0) for _ in range(len(basis))]
            nn = math.sqrt(sum(x * x for x in noise))
            coeffs = [math.cos(t)] + [math.sin(t) * (x / nn) for x in noise]
            comps = [query, *basis]
            v = [sum(c * x for c, x in zip(coeffs, col, strict=True)) for col in zip(*comps)]
            vn = math.sqrt(sum(x * x for x in v))
            vecs.append([x / vn for x in v])

        # Fixture self-check: every adjacent f32 similarity gap must exceed the
        # float16 quantisation noise floor (~3e-4) by a comfortable margin.
        m32 = np.array(vecs, dtype=np.float32)
        m32 /= np.linalg.norm(m32, axis=1, keepdims=True)
        q32 = np.asarray(query, dtype=np.float32)
        q32 = q32 / np.linalg.norm(q32)
        sims32 = np.sort(m32 @ q32)[::-1]
        assert float(np.min(sims32[:-1] - sims32[1:])) > 1e-3

        ids = []
        for v in vecs:
            ids.append(await _seed(db_session, date(2026, 1, 1), v))
        c = SemanticSearchCache()
        monkeypatch.setattr(c, "_backfill", lambda: None)
        await c.ensure_fresh(db_session)
        assert c.size == len(vecs)

        ranked = await c.search(db_session, query, ids, threshold=-1.0)

        # Full ordering identical to the legacy float32 math — not just top-k.
        top32 = [ids[i] for i in np.argsort(-sims32)]
        assert [eid for eid, _ in ranked] == top32
        # Scores agree well beyond the float16 noise floor.
        for (eid, s16), i32 in zip(ranked, np.argsort(-sims32), strict=True):
            assert eid == ids[int(i32)]
            assert s16 == pytest.approx(float(sims32[i32]), abs=5e-3)
