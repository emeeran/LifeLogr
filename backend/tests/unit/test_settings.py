"""Tests for the settings vacuum endpoint."""

import pytest
from httpx import AsyncClient


async def test_vacuum(client: AsyncClient):
    r = await client.post("/api/v1/settings/vacuum")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert isinstance(data["reclaimed_bytes"], int)
