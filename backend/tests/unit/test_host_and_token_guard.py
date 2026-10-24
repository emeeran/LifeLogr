"""Tests for the Host-header guard and the optional API token (main.py).

The guard is the DNS-rebinding defence: a page at a foreign host can point a
rebinding hostname at 127.0.0.1, and only the ``Host`` header betrays it. The
pytest harness sends a synthetic ``Host: test`` and is exempt (see main.py), so
these tests arm the guard by moving APP_ENV out of the test value.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import settings

# An endpoint that is cheap, DB-free, and unambiguously under /api/.
_API_PATH = "/api/v1/system/integrity"


@pytest.fixture
def armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Move APP_ENV off the test value so the Host guard is enforced."""
    monkeypatch.setattr(settings, "APP_ENV", "development")


async def _get(client: AsyncClient, host: str, **kwargs: Any) -> int:
    r = await client.get(_API_PATH, headers={"Host": host}, **kwargs)
    return r.status_code


class TestHostGuard:
    async def test_loopback_hosts_accepted(self, client: AsyncClient, armed: None) -> None:
        for host in (
            "127.0.0.1:18765",
            "localhost:8000",
            "[::1]:9000",
            "127.0.0.5:8000",
            "tauri.localhost",
        ):
            assert await _get(client, host) == 200, host

    async def test_foreign_host_rejected(self, client: AsyncClient, armed: None) -> None:
        r = await client.get(_API_PATH, headers={"Host": "evil.example.com"})
        assert r.status_code == 403
        assert "host" in r.json()["detail"].lower()

    async def test_rebinding_style_host_with_bind_port_rejected(
        self, client: AsyncClient, armed: None
    ) -> None:
        # The real attack: the attacker's domain resolving to 127.0.0.1. A
        # matching port must not whitewash a foreign hostname.
        assert await _get(client, f"evil.example.com:{settings.BIND_PORT}") == 403

    async def test_malformed_host_rejected(self, client: AsyncClient, armed: None) -> None:
        assert await _get(client, "not a host") == 403

    async def test_guard_idle_under_test_env(self, client: AsyncClient) -> None:
        """The synthetic harness Host is only tolerated while APP_ENV=test."""
        assert await _get(client, "test") == 200


class TestOptionalApiToken:
    @pytest.fixture
    def token(self, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(settings, "API_TOKEN", "s3cr3t-token")
        return "s3cr3t-token"

    async def test_api_requires_bearer_when_set(
        self, client: AsyncClient, token: str
    ) -> None:
        assert (await client.get(_API_PATH)).status_code == 401
        assert (
            await client.get(_API_PATH, headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        r = await client.get(_API_PATH, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    async def test_health_is_exempt(self, client: AsyncClient, token: str) -> None:
        """The liveness probe must stay reachable without a credential."""
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_unset_token_changes_nothing(self, client: AsyncClient) -> None:
        assert (await client.get(_API_PATH)).status_code == 200
