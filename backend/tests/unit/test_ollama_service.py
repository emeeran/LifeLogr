"""Integration tests for Ollama — mocked HTTP, real service logic."""
from unittest.mock import MagicMock, patch

from app.services.ollama_service import OllamaService


def _mock_response(json_data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


class TestGrammarCheck:
    async def test_grammar_check_with_suggestions(self):
        json_resp = {"response": '{"suggestions": [{"original": "I has", "corrected": "I have", "explanation": "Subject-verb agreement"}]}'}
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
        with patch.object(OllamaService, "_generate", return_value='{"misspellings": [{"word": "teh", "suggestion": "the"}]}'):
            svc = OllamaService()
            result = await svc.spell_check("I went to teh store")
        assert len(result.misspellings) == 1


class TestRewrite:
    async def test_rewrite_formal(self):
        with patch.object(OllamaService, "_generate", return_value="I would like to express my gratitude."):
            svc = OllamaService()
            result = await svc.rewrite("Thanks!", style="formal")
        assert result.rewritten_text


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
