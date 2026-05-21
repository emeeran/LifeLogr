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
