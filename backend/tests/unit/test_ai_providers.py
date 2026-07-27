"""AI providers: CRUD, encrypted-key secrecy, and active-provider routing."""

from __future__ import annotations

import pytest
import respx

from app.schemas.ai_provider import AIProviderCreate
from app.services.ai_provider_service import AIProviderService, invalidate_active_cache
from app.services.ollama_service import OllamaService


@pytest.fixture(autouse=True)
def _clear_active_cache():
    invalidate_active_cache()
    yield
    invalidate_active_cache()


@pytest.mark.asyncio
async def test_create_provider_hides_key_and_activates(client):
    r = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "OpenAI",
            "preset": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-test-secret",
            "is_active": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["has_key"] is True
    assert body["is_active"] is True
    assert "api_key" not in body and "api_key_encrypted" not in body

    providers = (await client.get("/api/v1/ai/providers")).json()
    assert len(providers) >= 1
    assert all("api_key" not in p and "api_key_encrypted" not in p for p in providers)


@pytest.mark.asyncio
async def test_activate_is_exclusive(client, db_session):
    a = await AIProviderService(db_session).create(
        AIProviderCreate(name="A", preset="openai", base_url="https://a/v1", model="m", is_active=True)
    )
    b = await AIProviderService(db_session).create(
        AIProviderCreate(name="B", preset="groq", base_url="https://b/v1", model="m")
    )
    r = await client.post(f"/api/v1/ai/providers/{b.id}/activate")
    assert r.status_code == 200
    active = next(p for p in (await client.get("/api/v1/ai/providers")).json() if p["id"] == b.id)
    stale = next(p for p in (await client.get("/api/v1/ai/providers")).json() if p["id"] == a.id)
    assert active["is_active"] is True and stale["is_active"] is False


@pytest.mark.asyncio
async def test_cloud_provider_routes_to_openai_endpoint(db_session):
    await AIProviderService(db_session).create(
        AIProviderCreate(
            name="Groq",
            preset="groq",
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
            api_key="gsk_test",
            is_active=True,
        )
    )
    with respx.mock(base_url="https://api.groq.com") as mock:
        mock.post("/openai/v1/chat/completions").respond(json=
            {"choices": [{"message": {"content": "cloud-reply"}}]}
        )
        out = await OllamaService()._generate("hello")
    # Cloud path extracts choices[0].message.content → proves OpenAI-compatible routing.
    assert out == "cloud-reply"


@pytest.mark.asyncio
async def test_no_active_provider_falls_back_to_ollama(db_session):
    # No provider created → active is None → native Ollama (/api/generate).
    with respx.mock(base_url="http://localhost:11434") as mock:
        mock.post("/api/generate").respond(json={"response": "ollama-reply"})
        out = await OllamaService()._generate("hello")
    # Native path extracts data["response"] → proves the Ollama fallback.
    assert out == "ollama-reply"


# ── test_connection / list_models error paths (respx) ────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_connection_returns_reported_model():
    from app.services.ai_provider_service import test_connection

    respx.post("https://provider.test/v1/chat/completions").respond(
        200, json={"model": "gpt-x", "choices": []}
    )
    assert await test_connection("https://provider.test/v1", "key", "gpt-x") == "gpt-x"


@pytest.mark.asyncio
@respx.mock
async def test_connection_raises_on_http_error():
    import httpx

    from app.services.ai_provider_service import test_connection

    respx.post("https://provider.test/v1/chat/completions").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        await test_connection("https://provider.test/v1", "key", "m")


@pytest.mark.asyncio
@respx.mock
async def test_connection_raises_on_timeout():
    import httpx

    from app.services.ai_provider_service import test_connection

    respx.post("https://provider.test/v1/chat/completions").mock(
        side_effect=httpx.ConnectTimeout("timeout")
    )
    with pytest.raises(httpx.HTTPError):
        await test_connection("https://provider.test/v1", "key", "m")


@pytest.mark.asyncio
@respx.mock
async def test_connection_without_key_omits_auth_header():
    from app.services.ai_provider_service import test_connection

    route = respx.post("https://provider.test/v1/chat/completions").respond(200, json={"model": "m"})
    await test_connection("https://provider.test/v1", None, "m")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_list_models_sorts_and_drops_empty_ids():
    from app.services.ai_provider_service import list_models

    respx.get("https://provider.test/v1/models").respond(
        200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": ""}, {"owned_by": "x"}]}
    )
    assert await list_models("https://provider.test/v1", "key") == [
        {"id": "a", "owned_by": ""},
        {"id": "b", "owned_by": ""},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_list_models_missing_data_returns_empty():
    from app.services.ai_provider_service import list_models

    respx.get("https://provider.test/v1/models").respond(200, json={})
    assert await list_models("https://provider.test/v1", "key") == []

