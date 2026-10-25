"""Integration tests for GET /api/v1/entries/geotags (map view data)."""

from __future__ import annotations

from httpx import AsyncClient
from tests.helpers.dayone_zip import PNG_1X1


async def _seed(client: AsyncClient, **kw) -> int:
    r = await client.post("/api/v1/entries", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_geotags_returns_geotagged_entries_with_thumbnail(client: AsyncClient) -> None:
    with_photo = await _seed(
        client,
        entry_date="2026-05-01",
        title="Ridge",
        body="hike",
        latitude=45.5,
        longitude=-122.6,
    )
    await client.post(
        "/api/v1/media",
        data={"entry_id": str(with_photo), "caption": ""},
        files={"file": ("ridge.png", PNG_1X1, "image/png")},
    )
    await _seed(client, entry_date="2026-05-02", title="No coords", body="plain")
    await _seed(
        client, entry_date="2026-05-03", title="Null island", body="x",
        latitude=0.0, longitude=0.0,
    )

    r = await client.get("/api/v1/entries/geotags")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["id"] == with_photo
    assert item["latitude"] == 45.5 and item["longitude"] == -122.6
    assert item["title"] == "Ridge"
    assert item["media_id"] is not None  # thumbnail reference for the popup
    # Bodies are never included in the map projection.
    assert "body" not in item


async def test_geotags_pagination_and_date_filter(client: AsyncClient) -> None:
    for day, lat in (("2026-05-01", 10.0), ("2026-06-01", 20.0), ("2026-07-01", 30.0)):
        await _seed(client, entry_date=day, body="x", latitude=lat, longitude=5.0)

    r = await client.get("/api/v1/entries/geotags", params={"limit": 1, "offset": 0})
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["items"][0]["latitude"] == 30.0  # newest first

    r = await client.get(
        "/api/v1/entries/geotags",
        params={"start_date": "2026-05-15", "end_date": "2026-06-30"},
    )
    assert [i["latitude"] for i in r.json()["items"]] == [20.0]


async def test_geotags_empty_journal_renders_empty(client: AsyncClient) -> None:
    r = await client.get("/api/v1/entries/geotags")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "offset": 0, "limit": 500}
