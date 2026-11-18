"""Ollama embedding fast-path — short timeout and single-flight dedupe."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import settings
from app.schemas.ai import AIStatusResponse
from app.services.ollama_service import (
    OllamaService,
    OllamaServiceError,
    _embed_inflight,
    _embed_timeout,
    _status_timeout,
)


@pytest.fixture(autouse=True)
def _clear_inflight():
    _embed_inflight.clear()
    yield
    _embed_inflight.clear()


@pytest.fixture(autouse=True)
def _clear_status_cache(monkeypatch):
    """The module-level status cache (60s TTL) must not answer for this test."""
    import app.services.ollama_service as mod

    monkeypatch.setattr(mod, "_cached_status", None)
    monkeypatch.setattr(mod, "_last_status_check", None)


class TestTimeouts:
    def test_embed_timeout_is_short_and_bounded(self, monkeypatch):
        monkeypatch.setattr(settings, "OLLAMA_TIMEOUT_SECONDS", 300)
        assert _embed_timeout() == 30.0
        monkeypatch.setattr(settings, "OLLAMA_TIMEOUT_SECONDS", 30)
        assert _embed_timeout() == 10.0
        monkeypatch.setattr(settings, "OLLAMA_TIMEOUT_SECONDS", 5)
        assert _embed_timeout() == 10.0  # floor

    def test_status_timeout_is_at_most_ten_seconds(self):
        assert _status_timeout() <= 10.0


class TestSingleFlight:
    async def test_concurrent_identical_calls_share_one_request(self):
        gate = asyncio.Event()

        async def slow_request(_provider, _text):
            await gate.wait()
            return [1.0, 0.0]

        svc = OllamaService()
        with patch.object(
            OllamaService, "get_active_provider", new_callable=AsyncMock, create=True
        ):
            with patch(
                "app.services.ai_provider_service.get_active_provider",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch.object(OllamaService, "_embed_request", side_effect=slow_request):
                    task = asyncio.gather(svc.embed("same query"), svc.embed("same query"))
                    await asyncio.sleep(0)  # let both callers register
                    inflight = [t for t in _embed_inflight.values()]
                    assert len(inflight) == 1  # one request, two waiters
                    gate.set()
                    results = await task
        assert results[0] == [1.0, 0.0] == results[1]

    async def test_different_texts_do_not_share(self):
        async def request(_provider, _text):
            return [0.0, 1.0]

        svc = OllamaService()
        with patch(
            "app.services.ai_provider_service.get_active_provider",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(OllamaService, "_embed_request", side_effect=request):
                await asyncio.gather(svc.embed("a"), svc.embed("b"))
        assert _embed_inflight == {}  # both completed and were cleaned up

    async def test_timeout_is_mapped_to_actionable_error(self):
        client = AsyncMock()
        client.post.side_effect = httpx.ReadTimeout("timed out")
        svc = OllamaService()
        with patch(
            "app.services.ai_provider_service.get_active_provider",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch("app.services.ollama_service._get_client", return_value=client):
                with pytest.raises(OllamaServiceError) as exc_info:
                    await svc.embed("q")
        assert "took too long" in str(exc_info.value)
        # And the request used the short timeout, not the generation one.
        assert client.post.call_args.kwargs["timeout"] == _embed_timeout()


class TestStatusTimeout:
    async def test_status_probe_uses_a_short_timeout(self):
        """The availability probe must never wait the generation timeout."""
        client = AsyncMock()
        client.get.return_value = httpx.Response(
            200, json={"models": [{"name": "m"}]}, request=httpx.Request("GET", "http://x")
        )
        svc = OllamaService()
        with patch("app.services.ollama_service._get_client", return_value=client):
            result = await svc.status()
        assert isinstance(result, AIStatusResponse)
        assert result.ollama_available is True
        assert client.get.call_args.kwargs["timeout"] == _status_timeout()
