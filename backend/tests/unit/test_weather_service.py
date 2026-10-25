"""Unit tests for the Open-Meteo weather service (cache, rounding, request shape)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import pytest
import respx

from app.core.config import settings
from app.services import weather_service

# Any recent date inside Open-Meteo's observed-past window.
DAY = date.today() - timedelta(days=3)

OPEN_METEO_RESPONSE = {
    "daily": {
        "time": [DAY.isoformat()],
        "temperature_2m_max": [84.4],
        "temperature_2m_min": [73.6],
        "weather_code": [2],
    },
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", tmp_path)
    return tmp_path


def test_round_coord_caps_at_two_decimals() -> None:
    """The explicit acceptance test: at most 2 decimals ever leave the device."""
    assert weather_service.round_coord(45.123456) == 45.12
    assert weather_service.round_coord(-122.6768) == -122.68
    for value in (0.0, 1.005, -33.8688197, 151.2093, 89.999999, -0.000001):
        rounded = weather_service.round_coord(value)
        assert abs(rounded * 100 - round(rounded * 100)) < 1e-9
        assert len(str(rounded).split(".")[-1]) <= 2 or rounded == round(rounded, 2)


@respx.mock
async def test_fetch_sends_rounded_coords_and_no_text(cache_dir) -> None:
    """Only the rounded coordinates + date go out — never entry content."""
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    result = await weather_service.conditions_for(45.123456, -122.67680, DAY)

    assert result == ("84 / 74 °F", "Partly cloudy")
    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["latitude"] == "45.12"
    assert params["longitude"] == "-122.68"
    assert params["start_date"] == DAY.isoformat() == params["end_date"]
    assert params["temperature_unit"] == "fahrenheit"
    # No journal content in any parameter or the URL itself.
    url = str(route.calls[0].request.url)
    assert "journal" not in url and "body" not in url


@respx.mock
async def test_disk_cache_prevents_second_request(cache_dir) -> None:
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    first = await weather_service.conditions_for(45.12, -122.68, DAY)
    second = await weather_service.conditions_for(45.12, -122.68, DAY)

    assert first == second == ("84 / 74 °F", "Partly cloudy")
    assert route.call_count == 1
    assert len(list(cache_dir.glob("*.json"))) == 1


@respx.mock
async def test_corrupt_cache_file_refetches(cache_dir) -> None:
    path = cache_dir / f"+45.12_-122.68_{DAY.isoformat()}.json"
    path.write_text("{not json")
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    result = await weather_service.conditions_for(45.12, -122.68, DAY)

    assert result == ("84 / 74 °F", "Partly cloudy")
    assert route.call_count == 1
    assert json.loads(path.read_text())["label"] == "Partly cloudy"


@respx.mock
async def test_date_older_than_window_skips_request(cache_dir) -> None:
    """Old entries are never backfilled — no request, no error."""
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)
    old_day = date.today() - timedelta(days=weather_service._MAX_PAST_DAYS + 1)

    result = await weather_service.conditions_for(45.12, -122.68, old_day)

    assert result is None
    assert route.call_count == 0


@respx.mock
async def test_network_error_returns_none(cache_dir) -> None:
    respx.get("https://api.open-meteo.com/v1/forecast").mock(side_effect=httpx.ConnectError("down"))

    assert await weather_service.conditions_for(45.12, -122.68, DAY) is None


@respx.mock
async def test_future_date_uses_forecast_window(cache_dir) -> None:
    """A not-yet-written entry (future date) is a forecast, not a skip."""
    future = date.today() + timedelta(days=5)
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(json=OPEN_METEO_RESPONSE)

    result = await weather_service.conditions_for(45.12, -122.68, future)

    assert result is not None
    assert route.calls[0].request.url.params["start_date"] == future.isoformat()


def test_wmo_labels_cover_open_meteo_codes() -> None:
    for code in (0, 2, 45, 61, 71, 95, 99):
        assert weather_service._WMO_LABELS[code]
