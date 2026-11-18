"""Integration tests for Ollama — mocked HTTP, real service logic."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ollama_service import (
    OllamaService,
    OllamaServiceError,
    is_reasoning_model,
)


def _mock_response(json_data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


class TestGrammarCheck:
    async def test_grammar_check_with_suggestions(self):
        json_resp = {
            "response": '{"suggestions": [{"original": "I has", "corrected": "I have", "explanation": "Subject-verb agreement"}]}'
        }
        with patch.object(OllamaService, "_generate", return_value=json_resp["response"]):
            svc = OllamaService()
            result = await svc.grammar_check("I has a cat")
        assert len(result.suggestions) == 1

    async def test_grammar_check_no_errors(self):
        with patch.object(OllamaService, "_generate", return_value='{"suggestions": []}'):
            svc = OllamaService()
            result = await svc.grammar_check("I have a cat")
        assert len(result.suggestions) == 0

    async def test_grammar_check_malformed(self):
        with patch.object(OllamaService, "_generate", return_value="not valid json"):
            svc = OllamaService()
            result = await svc.grammar_check("Some text")
        assert len(result.suggestions) == 0


class TestSpellCheck:
    async def test_spell_check_finds_misspellings(self):
        with patch.object(
            OllamaService,
            "_generate",
            return_value='{"misspellings": [{"word": "teh", "suggestion": "the"}]}',
        ):
            svc = OllamaService()
            result = await svc.spell_check("I went to teh store")
        assert len(result.misspellings) == 1


class TestRewrite:
    async def test_rewrite_formal(self):
        with patch.object(
            OllamaService, "_generate", return_value="I would like to express my gratitude."
        ):
            svc = OllamaService()
            result = await svc.rewrite("Thanks!", style="formal")
        assert result.rewritten_text

    async def test_rewrite_prompt_uses_requested_style(self):
        """Regression: rewrite() must interpolate the style, not hardcode 'professional'."""
        with patch.object(OllamaService, "_generate", return_value="hey there") as mock_generate:
            svc = OllamaService()
            await svc.rewrite("Thanks!", style="casual")
        prompt = mock_generate.call_args.args[0]
        assert "casual" in prompt
        assert "professional tone" not in prompt


class TestStatus:
    async def test_status_available_model_loaded(self):
        json_resp = {"models": [{"name": "llama3.2:3b"}]}
        resp = _mock_response(json_resp)
        with patch("httpx.AsyncClient.get", return_value=resp):
            import app.services.ollama_service as mod

            mod._cached_status = None
            mod._last_status_check = None
            svc = OllamaService()
            result = await svc.status()
        assert result.ollama_available is True
        assert result.model_loaded is True

    async def test_status_unavailable(self):
        import httpx

        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
            import app.services.ollama_service as mod

            mod._cached_status = None
            mod._last_status_check = None
            svc = OllamaService()
            result = await svc.status()
        assert result.ollama_available is False


class TestReasoningDetection:
    def test_is_reasoning_model_flags_thinking_models(self):
        for name in ("qwen3:4b", "deepseek-r1:8b", "qwq:32b", "gpt-oss:120b"):
            assert is_reasoning_model(name) is True, name

    def test_is_reasoning_model_ignores_standard_models(self):
        for name in ("gemma3:4b", "llama3.2:3b", "nomic-embed-text", ""):
            assert is_reasoning_model(name) is False, name


class TestGenerateErrors:
    """_generate must turn httpx failures into actionable OllamaServiceError."""

    async def test_timeout_raises_service_error_naming_model(self):
        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
        with patch("app.services.ollama_service._get_client", return_value=fake_client):
            svc = OllamaService()
            svc.model = "gemma3:4b"
            with pytest.raises(OllamaServiceError, match="gemma3:4b") as exc_info:
                await svc._generate("hi")
        # No reasoning hint for a standard model
        assert "qwen3" not in str(exc_info.value)

    async def test_timeout_for_reasoning_model_adds_hint(self):
        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
        with patch("app.services.ollama_service._get_client", return_value=fake_client):
            svc = OllamaService()
            svc.model = "qwen3:4b"
            with pytest.raises(OllamaServiceError, match="qwen3:4b") as exc_info:
                await svc._generate("hi")
        msg = str(exc_info.value)
        assert "gemma3:4b" in msg  # actionable recommendation present

    async def test_connect_error_raises_service_error(self):
        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("app.services.ollama_service._get_client", return_value=fake_client):
            svc = OllamaService()
            with pytest.raises(OllamaServiceError, match="Cannot reach Ollama"):
                await svc._generate("hi")
