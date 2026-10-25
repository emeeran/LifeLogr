"""Integration tests for the post-save weather auto-fill hook."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import respx

from app.core.config import settings
from app.services import weather_service

DAY = (date.today() - timedelta(days=3)).isoformat()
OPEN_METEO_RESPONSE = {
    "daily": {
        "time": [DAY],
        "temperature_2m_max": [84.4],
        "temperature_2m_min": [73.6],
        "weather_code": [2],
    },
}


async def _drain_weather_tasks() -> None:
    """Await the detached weather tasks so assertions see their writes."""
    for task in list(weather_service._pending_tasks):
        await task


@pytest.fixture
def weather_on(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_ENABLED", True)


@respx.mock
async def test_geotagged_save_creates_weather_event(client, db_session, weather_on, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    r = await client.post(
        "/api/v1/entries",
        json={"entry_date": DAY, "body": "Hiked Mount Tabor.", "latitude": 45.123456, "longitude": -122.6768},
    )
    assert r.status_code == 201
    entry_id = r.json()["id"]
    await _drain_weather_tasks()

    # The outbound request saw the rounded coordinates only.
    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["latitude"] == "45.12"
    assert params["longitude"] == "-122.68"

    detail = (await client.get(f"/api/v1/entries/{entry_id}")).json()
    weather = [e for e in detail.get("events", []) if e["kind"] == "weather"]
    assert len(weather) == 1
    assert weather[0]["content"] == "84 / 74 °F"
    assert weather[0]["label"] == "Partly cloudy"


@respx.mock
async def test_no_request_when_feature_off(client, db_session, tmp_path, monkeypatch):
    """The explicit acceptance criterion: fully functional with the feature off."""
    assert settings.WEATHER_ENABLED is False
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    r = await client.post(
        "/api/v1/entries",
        json={"entry_date": DAY, "body": "No weather please.", "latitude": 45.12, "longitude": -122.68},
    )
    assert r.status_code == 201
    await _drain_weather_tasks()

    assert route.call_count == 0
    detail = (await client.get(f"/api/v1/entries/{r.json()['id']}")).json()
    assert detail.get("events", []) == []


@respx.mock
async def test_no_request_without_coordinates(client, db_session, weather_on, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    r = await client.post("/api/v1/entries", json={"entry_date": DAY, "body": "No coords."})
    assert r.status_code == 201
    await _drain_weather_tasks()

    assert route.call_count == 0


@respx.mock
async def test_update_does_not_duplicate_weather_event(client, db_session, weather_on, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    r = await client.post(
        "/api/v1/entries",
        json={"entry_date": DAY, "body": "First save.", "latitude": 45.12, "longitude": -122.68},
    )
    entry_id = r.json()["id"]
    await _drain_weather_tasks()
    assert route.call_count == 1

    r2 = await client.patch(
        f"/api/v1/entries/{entry_id}",
        json={"entry_date": DAY, "body": "Edited body.", "latitude": 45.12, "longitude": -122.68},
    )
    assert r2.status_code == 200
    await _drain_weather_tasks()

    assert route.call_count == 1  # cached by coordinates+date AND idempotent on the entry
    detail = (await client.get(f"/api/v1/entries/{entry_id}")).json()
    assert len([e for e in detail.get("events", []) if e["kind"] == "weather"]) == 1


@respx.mock
async def test_import_does_not_fetch_weather(client, db_session, weather_on, tmp_path, monkeypatch):
    """Bulk imports stay network-free — the pipeline never schedules weather."""
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    payload = [
        {"entry_date": DAY, "title": "Imported", "body": "Geotagged import.", "latitude": 45.12, "longitude": -122.68},
    ]
    r = await client.post("/api/v1/entries/import", json=payload)
    assert r.status_code == 200
    await _drain_weather_tasks()

    assert route.call_count == 0
