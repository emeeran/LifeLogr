"""SemanticSearchCache — load, incremental mutation, self-healing, and ranking."""

import json
from datetime import date

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
        assert c.vectors.shape == (1, 2)

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
