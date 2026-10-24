"""Tests for settings-endpoint hardening: VACUUM off the request session and the
Ollama remote-host consent gate."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings

_SETTINGS = "/api/v1/settings"


@pytest.fixture(autouse=True)
def _no_runtime_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the endpoint from writing .runtime-settings.json into the data dir."""
    monkeypatch.setattr("app.routers.settings.persist_runtime_settings", lambda: None)


class TestVacuum:
    async def test_vacuum_runs_and_reports_reclaimed_bytes(self, client: AsyncClient) -> None:
        """VACUUM cannot run in a transaction — it needs its own AUTOCOMMIT connection."""
        r = await client.post(f"{_SETTINGS}/vacuum")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ok"
        assert isinstance(data["reclaimed_bytes"], int)
        assert data["reclaimed_bytes"] >= 0

    async def test_vacuum_succeeds_after_a_write(self, client: AsyncClient) -> None:
        """The open request session must not block the VACUUM statement."""
        await client.post(f"{_SETTINGS}/vacuum")
        await client.post(f"{_SETTINGS}/vacuum")
        # Session still usable afterwards.
        assert (await client.post(f"{_SETTINGS}/integrity-check")).status_code == 200
        assert (await client.get(f"{_SETTINGS}")).status_code == 200


class TestOllamaUrlGate:
    async def test_loopback_urls_accepted(self, client: AsyncClient) -> None:
        for url in ("http://localhost:11434", "http://127.0.0.5:11434", "http://[::1]:11434"):
            r = await client.put(_SETTINGS, json={"ai": {"ollama_base_url": url}})
            assert r.status_code == 200, (url, r.text)
            assert settings.OLLAMA_BASE_URL == url

    async def test_non_loopback_url_requires_confirm(self, client: AsyncClient) -> None:
        url = "http://192.168.1.50:11434"
        r = await client.put(_SETTINGS, json={"ai": {"ollama_base_url": url}})
        assert r.status_code == 400
        assert "confirm_remote" in r.json()["detail"]
        assert settings.OLLAMA_BASE_URL != url, "the URL must not be applied silently"

    async def test_non_loopback_url_allowed_with_explicit_confirm(
        self, client: AsyncClient
    ) -> None:
        url = "http://ollama.lan:11434"
        r = await client.put(
            _SETTINGS, json={"ai": {"ollama_base_url": url}, "confirm_remote": True}
        )
        assert r.status_code == 200, r.text
        assert settings.OLLAMA_BASE_URL == url

    async def test_non_http_scheme_still_rejected(self, client: AsyncClient) -> None:
        r = await client.put(_SETTINGS, json={"ai": {"ollama_base_url": "file:///etc/passwd"}})
        assert r.status_code == 400

    async def test_private_loopback_range_counts_as_loopback(self, client: AsyncClient) -> None:
        """The whole 127.0.0.0/8 is loopback, not just .1."""
        r = await client.put(_SETTINGS, json={"ai": {"ollama_base_url": "http://127.9.9.9:11434"}})
        assert r.status_code == 200
