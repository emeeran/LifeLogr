"""Integration tests for tags — CRUD, tree, conflict."""

from httpx import AsyncClient


class TestTagCreate:
    async def test_create_success(self, client: AsyncClient):
        r = await client.post("/api/v1/tags", json={"name": "travel"})
        assert r.status_code == 201
        assert r.json()["name"] == "travel"

    async def test_create_duplicate_returns_409(self, client: AsyncClient):
        await client.post("/api/v1/tags", json={"name": "travel"})
        r = await client.post("/api/v1/tags", json={"name": "travel"})
        assert r.status_code == 409

    async def test_create_with_parent(self, client: AsyncClient):
        parent = (await client.post("/api/v1/tags", json={"name": "places"})).json()
        r = await client.post("/api/v1/tags", json={"name": "europe", "parent_id": parent["id"]})
        assert r.status_code == 201
        assert r.json()["parent_id"] == parent["id"]


class TestTagRead:
    async def test_list_tree(self, client: AsyncClient):
        await client.post("/api/v1/tags", json={"name": "alpha"})
        await client.post("/api/v1/tags", json={"name": "beta"})
        r = await client.get("/api/v1/tags")
        assert r.status_code == 200
        names = [t["name"] for t in r.json()]
        assert "alpha" in names
        assert "beta" in names

    async def test_get_tag(self, client: AsyncClient):
        tag = (await client.post("/api/v1/tags", json={"name": "gamma"})).json()
        r = await client.get(f"/api/v1/tags/{tag['id']}")
        assert r.json()["name"] == "gamma"

    async def test_get_missing_returns_404(self, client: AsyncClient):
        r = await client.get("/api/v1/tags/9999")
        assert r.status_code == 404


class TestTagUpdate:
    async def test_rename(self, client: AsyncClient):
        tag = (await client.post("/api/v1/tags", json={"name": "old"})).json()
        r = await client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "new"})
        assert r.json()["name"] == "new"


class TestTagDelete:
    async def test_delete(self, client: AsyncClient):
        tag = (await client.post("/api/v1/tags", json={"name": "doomed"})).json()
        r = await client.delete(f"/api/v1/tags/{tag['id']}")
        assert r.status_code == 204
        r = await client.get(f"/api/v1/tags/{tag['id']}")
        assert r.status_code == 404


class TestTagListTreeCorrectness:
    """Regression cover for the batched (2-query) tag-list path.

    The list endpoints must populate ``children`` and ``entry_count`` for
    every root tag without per-tag queries — verified here by content, not
    just status/name, so a future change that breaks the in-memory tree
    build (e.g. confusing roots with children) is caught.
    """

    async def test_list_returns_children_and_entry_counts(self, client: AsyncClient):
        parent = (await client.post("/api/v1/tags", json={"name": "places"})).json()
        await client.post("/api/v1/tags", json={"name": "europe", "parent_id": parent["id"]})
        await client.post("/api/v1/tags", json={"name": "asia", "parent_id": parent["id"]})
        await client.post("/api/v1/tags", json={"name": "solo"})  # orphan root

        # Two live entries tagged with the parent; one soft-deleted (not counted).
        await client.post(
            "/api/v1/entries",
            json={"entry_date": "2024-01-01", "body": "a", "tag_ids": [parent["id"]]},
        )
        await client.post(
            "/api/v1/entries",
            json={"entry_date": "2024-01-02", "body": "b", "tag_ids": [parent["id"]]},
        )
        live = await client.post(
            "/api/v1/entries",
            json={"entry_date": "2024-01-03", "body": "c", "tag_ids": [parent["id"]]},
        )
        await client.delete(f"/api/v1/entries/{live.json()['id']}")

        r = await client.get("/api/v1/tags")
        assert r.status_code == 200
        by_name = {t["name"]: t for t in r.json()}

        # Roots only (children of a root are not themselves roots).
        assert set(by_name) == {"places", "solo"}
        places = by_name["places"]
        assert {c["name"] for c in places["children"]} == {"europe", "asia"}
        assert places["entry_count"] == 2  # soft-deleted entry excluded
        assert by_name["solo"]["entry_count"] == 0
        assert by_name["solo"]["children"] == []

    async def test_tree_endpoint_matches_list_at_root(self, client: AsyncClient):
        await client.post("/api/v1/tags", json={"name": "a"})
        await client.post("/api/v1/tags", json={"name": "b"})
        listed = {t["name"] for t in (await client.get("/api/v1/tags")).json()}
        tree = {t["name"] for t in (await client.get("/api/v1/tags/tree")).json()}
        assert listed == tree == {"a", "b"}

    async def test_list_filtered_by_parent(self, client: AsyncClient):
        parent = (await client.post("/api/v1/tags", json={"name": "root"})).json()
        await client.post("/api/v1/tags", json={"name": "child", "parent_id": parent["id"]})
        r = await client.get(f"/api/v1/tags?parent_id={parent['id']}")
        assert [t["name"] for t in r.json()] == ["child"]
