"""Batched tag listing — the N+1 fix plus response-shape parity."""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tag_service import TagService


async def _seed_tree(client: AsyncClient) -> dict[str, int]:
    root = (await client.post("/api/v1/tags", json={"name": "places"})).json()
    child = (
        await client.post("/api/v1/tags", json={"name": "europe", "parent_id": root["id"]})
    ).json()
    grandchild = (
        await client.post("/api/v1/tags", json={"name": "italy", "parent_id": child["id"]})
    ).json()
    other = (await client.post("/api/v1/tags", json={"name": "food"})).json()
    return {
        "root": root["id"],
        "child": child["id"],
        "grandchild": grandchild["id"],
        "other": other["id"],
    }


async def _count_statements(db_engine, coro):
    """Run ``coro`` and return (result, number of SQL statements executed)."""
    counter = {"n": 0}

    def _incr(*_args, **_kwargs) -> None:
        counter["n"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _incr)
    try:
        return await coro, counter["n"]
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _incr)


class TestBatchedListing:
    async def test_list_shape_is_unchanged(self, client: AsyncClient):
        """children = direct children only; entry_count counts non-deleted entries."""
        ids = await _seed_tree(client)

        # Two entries tagged "europe", one soft-deleted.
        for _ in range(2):
            await client.post(
                "/api/v1/entries",
                json={
                    "entry_date": date(2026, 5, 1).isoformat(),
                    "body": "x",
                    "tag_ids": [ids["child"]],
                },
            )
        deleted = (
            await client.post(
                "/api/v1/entries",
                json={"entry_date": date(2026, 5, 2).isoformat(), "body": "y", "tag_ids": [ids["child"]]},
            )
        ).json()
        await client.delete(f"/api/v1/entries/{deleted['id']}")

        tags = {t["name"]: t for t in (await client.get("/api/v1/tags")).json()}
        # Only roots are listed; children appear nested (unchanged behaviour).
        assert set(tags) == {"places", "food"}
        assert tags["places"]["children"] == [{"id": ids["child"], "name": "europe"}]
        assert tags["places"]["parent_id"] is None
        assert tags["food"]["children"] == []

        europe = (await client.get(f"/api/v1/tags/{ids['child']}")).json()
        assert europe["children"] == [{"id": ids["grandchild"], "name": "italy"}]
        assert europe["parent_id"] == ids["root"]
        # Only live entries are counted.
        assert europe["entry_count"] == 2
        assert (await client.get(f"/api/v1/tags/{ids['root']}")).json()["entry_count"] == 0

    async def test_tree_endpoint_matches_list(self, client: AsyncClient):
        await _seed_tree(client)
        listed = sorted(t["name"] for t in (await client.get("/api/v1/tags")).json())
        tree = sorted(t["name"] for t in (await client.get("/api/v1/tags/tree")).json())
        assert listed == tree

    async def test_single_tag_lookup_is_correct(self, client: AsyncClient):
        ids = await _seed_tree(client)
        r = await client.get(f"/api/v1/tags/{ids['root']}")
        assert r.status_code == 200
        body = r.json()
        assert body["children"] == [{"id": ids["child"], "name": "europe"}]
        assert body["entry_count"] == 0

    async def test_listing_is_bounded_queries(self, client: AsyncClient, db_engine):
        """N tags must not cost 2N+1 queries."""
        for i in range(6):
            await client.post("/api/v1/tags", json={"name": f"tag-{i}"})

        async def _list():
            return (await client.get("/api/v1/tags")).json()

        _result, n = await _count_statements(db_engine, _list())
        # 1 (tags) + 1 (grouped children) + 1 (GROUP BY count); allow a couple
        # of framework statements (session baseline, savepoint flush).
        assert n <= 6, f"tag listing issued {n} statements — N+1 regression?"


class TestBatchHelpers:
    async def test_children_by_parent_and_entry_counts(self, db_session: AsyncSession):
        from datetime import date as date_cls

        from app.models.entry import Entry
        from app.models.tag import EntryTag

        from app.schemas.tag import TagCreate

        svc = TagService(db_session)
        parent = await svc.create(TagCreate(name="p"))
        child = await svc.create(TagCreate(name="c", parent_id=parent.id))
        assert await svc.children_by_parent([]) == {}
        assert await svc.entry_counts([]) == {}

        entry = Entry(entry_date=date_cls(2026, 5, 1), body="tagged")
        db_session.add(entry)
        await db_session.flush()
        db_session.add(EntryTag(entry_id=entry.id, tag_id=child.id))
        await db_session.commit()

        children = await svc.children_by_parent([parent.id, child.id])
        assert [t.id for t in children[parent.id]] == [child.id]
        assert children[child.id] == []

        counts = await svc.entry_counts([parent.id, child.id])
        assert counts == {parent.id: 0, child.id: 1}
