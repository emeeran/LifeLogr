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

    for name in ("cloud_ai", "cloud_backup", "web_clip", "ocr", "embeddings", "read_aloud"):
        assert name in data, name

    for name in ("cloud_ai", "web_clip", "ocr", "embeddings", "read_aloud"):
        assert isinstance(data[name]["leaves_device"], bool), name
        assert isinstance(data[name]["note"], str) and data[name]["note"], name

    assert data["web_clip"]["leaves_device"] is False
    assert data["ocr"]["leaves_device"] is False
