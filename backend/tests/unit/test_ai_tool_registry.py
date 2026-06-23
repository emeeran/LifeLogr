"""Unit tests for the generic AI tool registry and OllamaService.run_generic_tool."""

from unittest.mock import patch

import pytest

from app.services.ollama_service import OllamaService


class TestRunGenericTool:
    async def test_summarize_returns_stripped_text(self):
        with patch.object(OllamaService, "_generate", return_value="  a concise summary.  "):
            svc = OllamaService()
            result = await svc.run_generic_tool("summarize", "Some long text.", None)
        assert result == "a concise summary."

    async def test_translate_uses_param_in_prompt(self):
        with patch.object(OllamaService, "_generate", return_value="bonjour") as mock_generate:
            svc = OllamaService()
            await svc.run_generic_tool("translate", "Hello", "French")
        prompt = mock_generate.call_args.args[0]
        assert "French" in prompt

    async def test_translate_uses_default_param_when_none(self):
        with patch.object(OllamaService, "_generate", return_value="hola") as mock_generate:
            svc = OllamaService()
            await svc.run_generic_tool("translate", "Hello", None)
        prompt = mock_generate.call_args.args[0]
        assert "Spanish" in prompt

    async def test_unknown_tool_raises_keyerror(self):
        svc = OllamaService()
        with pytest.raises(KeyError):
            await svc.run_generic_tool("nope", "text", None)

    async def test_invalid_param_raises_valueerror(self):
        svc = OllamaService()
        with pytest.raises(ValueError):
            await svc.run_generic_tool("translate", "text", "Klingon")

    async def test_paramless_tool_ignores_param(self):
        """A tool without a param spec accepts (and ignores) any param value."""
        with patch.object(OllamaService, "_generate", return_value="summary"):
            svc = OllamaService()
            result = await svc.run_generic_tool("summarize", "text", "ignored")
        assert result == "summary"
