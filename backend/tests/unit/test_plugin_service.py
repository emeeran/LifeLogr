"""Integration tests for plugins — install, CRUD, hooks."""
from httpx import AsyncClient


class TestPluginCRUD:
    async def test_install(self, client: AsyncClient):
        r = await client.post("/api/v1/plugins", json={
            "name": "test-plugin",
            "version": "1.0",
            "entry_point": "test_plugin.main",
        })
        assert r.status_code == 201
        assert r.json()["name"] == "test-plugin"

    async def test_list_plugins(self, client: AsyncClient):
        await client.post("/api/v1/plugins", json={
            "name": "p1", "version": "1.0", "entry_point": "p1.main",
        })
        r = await client.get("/api/v1/plugins")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_get_plugin(self, client: AsyncClient):
        p = (await client.post("/api/v1/plugins", json={
            "name": "p2", "version": "2.0", "entry_point": "p2.main",
        })).json()
        r = await client.get(f"/api/v1/plugins/{p['id']}")
        assert r.json()["name"] == "p2"

    async def test_get_missing_404(self, client: AsyncClient):
        r = await client.get("/api/v1/plugins/9999")
        assert r.status_code == 404

    async def test_enable_disable(self, client: AsyncClient):
        p = (await client.post("/api/v1/plugins", json={
            "name": "p3", "version": "1.0", "entry_point": "p3.main",
        })).json()
        r = await client.post(f"/api/v1/plugins/{p['id']}/disable")
        assert r.json()["is_enabled"] is False
        r = await client.post(f"/api/v1/plugins/{p['id']}/enable")
        assert r.json()["is_enabled"] is True

    async def test_uninstall(self, client: AsyncClient):
        p = (await client.post("/api/v1/plugins", json={
            "name": "p4", "version": "1.0", "entry_point": "p4.main",
        })).json()
        r = await client.delete(f"/api/v1/plugins/{p['id']}")
        assert r.status_code == 204


class TestHookManager:
    async def test_register_and_dispatch(self, client: AsyncClient):
        from app.services.plugin_manager import hook_manager

        called = []
        fn = lambda x: called.append(x)  # noqa: E731
        hook_manager.register("test_hook", fn, priority=10)
        await hook_manager.dispatch("test_hook", "hello")
        assert called == ["hello"]
        hook_manager.unregister("test_hook", fn)

    async def test_hooks_registry(self, client: AsyncClient):
        r = await client.get("/api/v1/plugins/hooks/registry")
        assert r.status_code == 200
