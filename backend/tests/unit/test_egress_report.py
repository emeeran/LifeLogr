"""Tests for the egress report — the Privacy tab's audit of data leaving the device."""

from __future__ import annotations

from httpx import AsyncClient


async def test_egress_report_includes_read_aloud(client: AsyncClient) -> None:
    """Read-aloud must be listed: Edge TTS sends entry text to Microsoft."""
    r = await client.get("/api/v1/system/egress-report")
    assert r.status_code == 200
    data = r.json()

    surface = data["read_aloud"]
    assert surface["leaves_device"] is True
    assert "Edge" in surface["note"] or "Edge" in surface.get("provider", "")
    assert surface["note"].strip()


async def test_egress_report_schema_is_stable(client: AsyncClient) -> None:
    """Every surface keeps the leaves_device + note shape the Privacy tab renders."""
    r = await client.get("/api/v1/system/egress-report")
    assert r.status_code == 200
    data = r.json()

    for name in ("cloud_ai", "cloud_backup", "web_clip", "ocr", "embeddings", "read_aloud", "weather", "map_tiles"):
        assert name in data, name

    for name in ("cloud_ai", "web_clip", "ocr", "embeddings", "read_aloud", "weather", "map_tiles"):
        assert isinstance(data[name]["leaves_device"], bool), name
        assert isinstance(data[name]["note"], str) and data[name]["note"], name

    assert data["web_clip"]["leaves_device"] is False
    assert data["ocr"]["leaves_device"] is False


async def test_weather_surface_reflects_toggle(client: AsyncClient, monkeypatch) -> None:
    """The weather row reports live opt-in state — off by default, on when enabled."""
    from app.core.config import settings

    assert settings.WEATHER_ENABLED is False
    r = await client.get("/api/v1/system/egress-report")
    weather = r.json()["weather"]
    assert weather["leaves_device"] is False
    assert "Open-Meteo" in weather.get("provider", "")
    assert "rounded" in weather["note"]

    monkeypatch.setattr(settings, "WEATHER_ENABLED", True)
    r = await client.get("/api/v1/system/egress-report")
    assert r.json()["weather"]["leaves_device"] is True


async def test_map_tiles_surface_reflects_toggle(client: AsyncClient, monkeypatch) -> None:
    """Plot-only default (no egress); the row goes live with the opt-in."""
    from app.core.config import settings

    assert settings.MAP_ONLINE_TILES is False
    r = await client.get("/api/v1/system/egress-report")
    surface = r.json()["map_tiles"]
    assert surface["leaves_device"] is False
    assert "plot-only" in surface["note"]

    monkeypatch.setattr(settings, "MAP_ONLINE_TILES", True)
    r = await client.get("/api/v1/system/egress-report")
    assert r.json()["map_tiles"]["leaves_device"] is True
