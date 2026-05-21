"""Integration tests for geotagging — set, remove, map view."""
from httpx import AsyncClient


async def _entry(client: AsyncClient, date="2026-05-01"):
    r = await client.post("/api/v1/entries", json={"entry_date": date, "body": "Geo"})
    return r.json()


class TestGeotagging:
    async def test_set_geotag(self, client: AsyncClient):
        e = await _entry(client)
        r = await client.put(f"/api/v1/entries/{e['id']}/geotag",
                             json={"latitude": 51.5, "longitude": -0.12, "location_name": "London"})
        assert r.status_code == 200
        assert r.json()["latitude"] == 51.5

    async def test_remove_geotag(self, client: AsyncClient):
        e = await _entry(client)
        await client.put(f"/api/v1/entries/{e['id']}/geotag",
                         json={"latitude": 48.85, "longitude": 2.35})
        r = await client.delete(f"/api/v1/entries/{e['id']}/geotag")
        assert r.status_code == 204

    async def test_map_view(self, client: AsyncClient):
        e = await _entry(client)
        await client.put(f"/api/v1/entries/{e['id']}/geotag",
                         json={"latitude": 40.71, "longitude": -74.0, "location_name": "NYC"})
        r = await client.get("/api/v1/entries/map")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_geotag_missing_entry_404(self, client: AsyncClient):
        r = await client.put("/api/v1/entries/9999/geotag", json={"latitude": 0, "longitude": 0})
        assert r.status_code == 404
