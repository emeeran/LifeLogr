"""Tests for the shared AI system prompt, entry context, and retry temperature.

Covers spec.md §10: AI1 (system message on every provider path), AI2 (entry
context in the system channel, absent fields as "unset"), and AI5 (retry bumps
temperature). Requests are captured with an httpx MockTransport so the actual
wire payload of each provider path is asserted.
"""

import json

import httpx
import pytest

from app.services.ollama_service import (
    SYSTEM_PROMPT,
    EntryContext,
    OllamaService,
    build_system_message,
    entry_context_from,
    format_entry_context,
    retry_temperature,
)


def _patch_client(monkeypatch: pytest.MonkeyPatch, captured: list[dict], response: dict) -> None:
    """Point the service's shared client at a capturing MockTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ollama_service._get_client",
        lambda: httpx.AsyncClient(transport=transport, timeout=5),
    )


_OLLAMA_RESPONSE = {"response": "ok"}
_OPENAI_RESPONSE = {"choices": [{"message": {"content": "ok"}}]}


class TestSystemMessageEveryProviderPath:
    """T-AI1: both provider paths carry the shared system message verbatim."""

    async def test_ollama_path_sends_system_field(self, monkeypatch):
        captured: list[dict] = []
        _patch_client(monkeypatch, captured, _OLLAMA_RESPONSE)
        svc = OllamaService()
        await svc.grammar_check("I has a cat")
        body = captured[0]
        # The system message is the shared prompt plus the entry-context line
        # (all fields unset — no entry context was supplied).
        assert body["system"].startswith(SYSTEM_PROMPT)
        assert "date unset" in body["system"]
        assert "never moralize" in body["system"]
        # Tool-specific behavior stays in the user message.
        assert body["prompt"].startswith("You are a grammar and spelling checker")

    async def test_openai_path_sends_system_role_message(self, monkeypatch):
        captured: list[dict] = []
        _patch_client(monkeypatch, captured, _OPENAI_RESPONSE)

        class FakeProvider:
            preset = "openai"
            base_url = "https://api.example.com/v1"
            model = "gpt-x"
            api_key_encrypted = None

        async def fake_active_provider():
            return FakeProvider()

        monkeypatch.setattr(
            "app.services.ai_provider_service.get_active_provider", fake_active_provider
        )
        svc = OllamaService()
        await svc.grammar_check("I has a cat")
        messages = captured[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"].startswith(SYSTEM_PROMPT)
        assert messages[1]["role"] == "user"

    async def test_registry_tools_add_no_competing_persona(self, monkeypatch):
        """T-AI1: folded registry tools carry no 'You are a …' persona line."""
        captured: list[dict] = []
        _patch_client(monkeypatch, captured, _OLLAMA_RESPONSE)
        svc = OllamaService()
        await svc.run_generic_tool("summarize", "Some text.")
        assert "You are" not in captured[0]["prompt"]
        assert captured[0]["system"].startswith(SYSTEM_PROMPT)


class TestEntryContext:
    """T-AI2: entry context rides in the system channel; absent fields = unset."""

    def test_all_fields_render(self):
        line = format_entry_context(
            EntryContext(date="2026-10-27", title="Trip", mood="calm", tags=["work", "travel"])
        )
        assert (
            'date 2026-10-27; title "Trip"; mood calm; tags [work, travel]' in line
        )
        assert line.endswith("excerpt of a longer entry.")

    def test_missing_fields_render_as_unset(self):
        line = format_entry_context(EntryContext(date="2026-10-27"))
        assert 'title "unset"' in line
        assert "mood unset" in line
        assert "tags [unset]" in line

    def test_no_context_renders_all_unset(self):
        line = format_entry_context(None)
        assert "date unset" in line
        assert "mood unset" in line

    def test_system_message_embeds_context(self):
        msg = build_system_message(EntryContext(title="T"))
        assert msg == f"{SYSTEM_PROMPT}\n\n{format_entry_context(EntryContext(title='T'))}"

    async def test_context_reaches_wire_payload(self, monkeypatch):
        captured: list[dict] = []
        _patch_client(monkeypatch, captured, _OLLAMA_RESPONSE)
        svc = OllamaService()
        await svc.run_generic_tool(
            "summarize",
            "Some text.",
            entry_context=EntryContext(date="2026-10-27", title="Trip", mood=None),
        )
        system = captured[0]["system"]
        assert 'title "Trip"' in system
        assert "mood unset" in system

    def test_entry_context_from_payload(self):
        payload = {"date": "2026-10-27", "title": "T", "mood": None, "tags": ["a"]}
        ctx = entry_context_from(payload)
        assert ctx == EntryContext(date="2026-10-27", title="T", mood=None, tags=("a",))
        assert entry_context_from(None) == EntryContext()


class TestRetryTemperature:
    """T-AI5: retries vary sampling temperature, capped."""

    def test_base_attempt_unchanged(self):
        assert retry_temperature(0.5, 0) == 0.5

    def test_each_retry_bumps(self):
        assert retry_temperature(0.5, 1) == pytest.approx(0.7)
        assert retry_temperature(0.5, 2) == pytest.approx(0.9)

    def test_capped_at_max(self):
        assert retry_temperature(0.5, 10) == 1.0

    async def test_wire_temperature_differs_per_attempt(self, monkeypatch):
        captured: list[dict] = []
        _patch_client(monkeypatch, captured, _OLLAMA_RESPONSE)
        svc = OllamaService()
        await svc.run_generic_tool("rewrite", "text", "as-is", attempt=0)
        await svc.run_generic_tool("rewrite", "text", "as-is", attempt=1)
        temps = [c["options"]["temperature"] for c in captured]
        assert temps[0] == pytest.approx(0.5)
        assert temps[1] == pytest.approx(0.7)
