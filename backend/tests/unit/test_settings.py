"""Tests for settings endpoints: vacuum and integrity-check."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_vacuum(client: AsyncClient):
    r = await client.post("/api/v1/settings/vacuum")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert isinstance(data["reclaimed_bytes"], int)


@pytest.mark.asyncio
async def test_integrity_check(client: AsyncClient):
    r = await client.post("/api/v1/settings/integrity-check")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["message"] == "ok"
