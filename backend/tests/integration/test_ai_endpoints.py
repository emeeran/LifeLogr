"""Integration tests for the generic AI tool endpoint."""

from unittest.mock import patch

from app.services.ollama_service import OllamaService


class TestGenericToolEndpoint:
    async def test_known_tool_returns_result(self, client):
        with patch.object(OllamaService, "_generate", return_value="a concise summary"):
            resp = await client.post("/api/v1/ai/tool/summarize", json={"text": "Some text."})
        assert resp.status_code == 200
        assert resp.json() == {"result": "a concise summary"}

    async def test_unknown_tool_returns_404(self, client):
        resp = await client.post("/api/v1/ai/tool/nope", json={"text": "Some text."})
        assert resp.status_code == 404

    async def test_invalid_param_returns_400(self, client):
        resp = await client.post(
            "/api/v1/ai/tool/translate", json={"text": "Hi", "param": "Klingon"}
        )
        assert resp.status_code == 400

    async def test_empty_text_returns_422(self, client):
        resp = await client.post("/api/v1/ai/tool/summarize", json={"text": ""})
        assert resp.status_code == 422
