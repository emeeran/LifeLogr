"""Tests for the main.py hardening odds and ends: rate-limiter memory/Retry-After,
SPA catch-all behaviour for API paths, and the cached Ollama health probe."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.main as main
from app.core.config import settings


class TestSpaCatchAll:
    async def test_unknown_api_path_returns_404_json(self, client: AsyncClient) -> None:
        """An unknown /api/* path must never be answered with the SPA's index.html."""
        r = await client.get("/api/v1/does-not-exist")
        assert r.status_code == 404
        assert r.json() == {"detail": "Not found"}

    async def test_unknown_api_root_returns_404_json(self, client: AsyncClient) -> None:
        assert (await client.get("/api")).status_code == 404

    async def test_client_routes_still_serve_index(self, client: AsyncClient) -> None:
        r = await client.get("/entries/some-view")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestHealthOllamaProbeCache:
    async def test_probe_result_is_cached_for_ttl(self, monkeypatch) -> None:
        """A burst of health checks must not fire a burst of Ollama calls."""
        import respx

        monkeypatch.setattr(main, "_ollama_probe", (0.0, "unknown"))
        with respx.mock:
            route = respx.get(f"{settings.OLLAMA_BASE_URL}/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
            assert await main._ollama_probe_status() == "ok"
            assert await main._ollama_probe_status() == "ok"
            assert route.call_count == 1, "second call inside the TTL must reuse the result"

            # Force the TTL to elapse and the probe must run again.
            checked_at, status = main._ollama_probe
            monkeypatch.setattr(main, "_ollama_probe", (checked_at - 31.0, status))
            assert await main._ollama_probe_status() == "ok"
            assert route.call_count == 2

    async def test_health_reports_cached_probe(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """/health surfaces the cached status and never re-probes inside the TTL."""
        import time as _time

        monkeypatch.setattr(main, "_ollama_probe", (_time.time(), "unreachable"))
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["checks"]["ollama"] == "unreachable"


class TestRateLimiter:
    @pytest.fixture
    def production(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "APP_ENV", "production")
        main._rate_store.clear()
        monkeypatch.setattr(main, "RATE_LIMIT", 2)
        monkeypatch.setattr(main, "RATE_WINDOW", 60.0)
        return main._rate_store

    async def test_429_carries_retry_after(self, client: AsyncClient, production) -> None:
        for _ in range(2):
            r = await client.get("/api/v1/system/integrity", headers={"Host": "127.0.0.1:18765"})
            assert r.status_code == 200
        r = await client.get("/api/v1/system/integrity", headers={"Host": "127.0.0.1:18765"})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

    async def test_stale_keys_are_reclaimed(self, client: AsyncClient, production) -> None:
        """No empty per-IP lists may linger once a window has elapsed."""
        for _ in range(2):
            await client.get("/api/v1/system/integrity", headers={"Host": "127.0.0.1:18765"})
        # Age every timestamp past the window, then let a new request prune.
        for key, hits in list(production.items()):
            production[key] = [t - (main.RATE_WINDOW + 1) for t in hits]
        await client.get("/api/v1/system/integrity", headers={"Host": "127.0.0.1:18765"})
        assert all(hits for hits in production.values()), production
        assert all(len(hits) == 1 for hits in production.values()), production
