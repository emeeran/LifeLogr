"""Ollama API client for AI text assistance, embeddings, and analysis."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core import security
from app.core.config import settings
from app.schemas.ai import (
    AIStatusResponse,
    GrammarCheckResponse,
    RewriteResponse,
    SpellCheckResponse,
    Suggestion,
)

logger = logging.getLogger(__name__)

# Substrings (lowercased) that identify reasoning / "thinking" models. These emit
# long <think>…</think> chains before answering and are unusably slow on CPU —
# every editor AI tool silently stalls if one is configured. Used to add an
# actionable hint to timeout errors and to warn in the settings UI.
_REASONING_MARKERS = (
    "qwen3",
    "deepseek-r1",
    "qwq",
    "gpt-oss",
    "magistral",
    "openthinker",
    "thinker",
    "reasoning",
    "nemotron",
)

_REASONING_TIMEOUT_HINT = (
    " Reasoning/thinking models (e.g. qwen3) are extremely slow on CPU — "
    "switch to a standard model like gemma3:4b in Settings → AI."
)


def is_reasoning_model(name: str) -> bool:
    """Heuristic: does this Ollama model name look like a reasoning model?"""
    lowered = (name or "").lower()
    return any(marker in lowered for marker in _REASONING_MARKERS)


class OllamaServiceError(Exception):
    """Actionable Ollama failure (timeout, unreachable, bad status).

    Mapped to HTTP 504 by the app's exception handler so the client sees a
    helpful message instead of a generic 500 after a long hang.
    """


# Cache for model availability check
_last_status_check: datetime | None = None
_cached_status: AIStatusResponse | None = None
_STATUS_CACHE_TTL_SECONDS = 60

# Embedding / availability requests are small but sit on the critical path of
# every semantic & hybrid search, and they shared the 300s generation timeout —
# one hung Ollama stalled every search for five minutes. They get a short
# dedicated timeout derived as a fraction of the configured one (clamped), so a
# user who raises OLLAMA_TIMEOUT_SECONDS for a slow box still gets a bounded
# search-path failure.
_EMBED_TIMEOUT_FLOOR_SECONDS = 10.0
_EMBED_TIMEOUT_CAP_SECONDS = 30.0


def _embed_timeout() -> float:
    """Short timeout for embedding requests (fraction of the generation timeout)."""
    return float(
        min(
            _EMBED_TIMEOUT_CAP_SECONDS,
            max(_EMBED_TIMEOUT_FLOOR_SECONDS, settings.OLLAMA_TIMEOUT_SECONDS / 10),
        )
    )


def _status_timeout() -> float:
    """Short timeout for the availability probe (always snappy)."""
    return float(min(10.0, _embed_timeout()))


# Single-flight guard for embeddings: text → in-flight request. Concurrent
# searches for the same query share one call instead of stacking identical ones.
_embed_inflight: dict[str, asyncio.Task[list[float]]] = {}


# Module-level shared httpx client. Every OllamaService() instance
# previously opened its own ``AsyncClient`` (new TCP connection pool per
# call). For a long-lived desktop process with repeated embed/analyse calls,
# a single shared client reuses connections and avoids the overhead of
# creating/tearing down a pool on every request.
_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT_SECONDS)
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared client (call on app shutdown)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


class OllamaService:
    """Client for local Ollama instance providing AI text assistance."""

    def __init__(self) -> None:
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT_SECONDS

    async def _generate(
        self,
        prompt: str,
        model: str | None = None,
        num_predict: int = 2048,
        temperature: float | None = None,
    ) -> str:
        """Send a completion request and return the response text.

        Routes through the active AI provider: an OpenAI-compatible cloud
        provider (OpenAI/Groq/OpenRouter/Kimi/Gemini/custom) if one is active,
        otherwise local Ollama (the default, or an ollama-preset provider).

        Raises :class:`OllamaServiceError` with an actionable message if the
        request times out, the host is unreachable, or returns an error status.
        """
        from app.services.ai_provider_service import get_active_provider

        provider = await get_active_provider()
        if provider is not None and provider.preset != "ollama":
            api_key = (
                security.decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else None
            )
            return await self._generate_openai(
                provider.base_url,
                api_key,
                model or provider.model,
                prompt,
                num_predict,
                temperature,
            )
        if provider is not None:  # ollama preset
            base_url = provider.base_url or self.base_url
            used_model = model or provider.model
        else:
            base_url = self.base_url
            used_model = model or self.model
        return await self._generate_ollama(base_url, used_model, prompt, num_predict, temperature)

    async def _generate_ollama(
        self,
        base_url: str,
        used_model: str,
        prompt: str,
        num_predict: int,
        temperature: float | None,
    ) -> str:
        options: dict[str, Any] = {"num_predict": num_predict}
        if temperature is not None:
            options["temperature"] = temperature
        client = _get_client()
        try:
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": used_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options,
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            hint = _REASONING_TIMEOUT_HINT if is_reasoning_model(used_model) else ""
            raise OllamaServiceError(
                f"Model '{used_model}' took too long to respond "
                f"(timed out after {self.timeout}s).{hint}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaServiceError(
                f"Ollama rejected the request for '{used_model}' (HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:  # ConnectError, ReadError, etc.
            raise OllamaServiceError(f"Cannot reach Ollama at {base_url}: {exc}") from exc
        data: dict[str, Any] = response.json()
        return str(data.get("response", ""))

    async def _generate_openai(
        self,
        base_url: str,
        api_key: str | None,
        used_model: str,
        prompt: str,
        num_predict: int,
        temperature: float | None,
    ) -> str:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body: dict[str, Any] = {
            "model": used_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": num_predict,
        }
        if temperature is not None:
            body["temperature"] = temperature
        client = _get_client()
        try:
            response = await client.post(f"{base_url}/chat/completions", json=body, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OllamaServiceError(
                f"Provider took too long to respond (timed out after {self.timeout}s)."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200] if exc.response is not None else ""
            if exc.response.status_code == 404 and "model_not_found" in detail:
                raise OllamaServiceError(
                    f"Provider does not recognize model '{used_model}'. "
                    "It may have been retired — pick a current model in "
                    "Settings → AI (↻ refreshes the provider's model list)."
                ) from exc
            raise OllamaServiceError(
                f"Provider rejected the request for '{used_model}' "
                f"(HTTP {exc.response.status_code}). {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaServiceError(f"Cannot reach provider at {base_url}: {exc}") from exc
        data: dict[str, Any] = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", ""))

    async def grammar_check(self, text: str, language: str = "en") -> GrammarCheckResponse:
        """Check grammar and spelling, returning suggestions and corrected text."""
        prompt = (
            f"You are a grammar and spelling checker for {language} text. "
            f"Analyze the following text and return a JSON object with this exact structure:\n"
            f'{{"corrected_text": "...", "suggestions": [{{"offset": 0, "length": 0, '
            f'"original": "...", "suggestion": "...", "rule_id": "...", "message": "..."}}]}}\n\n'
            f"Text to check:\n{text}\n\n"
            f"Return ONLY the raw JSON object — no markdown code fence, no commentary."
        )
        raw = await self._generate(prompt)
        return self._parse_grammar_response(text, raw)

    async def spell_check(self, text: str, language: str = "en") -> SpellCheckResponse:
        """Spell-check only — identify misspellings without grammar corrections."""
        prompt = (
            f"You are a spell-checker for {language} text. "
            f"Find only spelling errors (not grammar). Return a JSON object:\n"
            f'{{"corrected_text": "...", "misspellings": [{{"offset": 0, "length": 0, '
            f'"original": "...", "suggestion": "...", "rule_id": "SPELL", "message": "..."}}]}}\n\n'
            f"Text to check:\n{text}\n\n"
            f"Return ONLY the raw JSON object — no markdown code fence, no commentary."
        )
        raw = await self._generate(prompt)
        parsed = self._parse_grammar_response(text, raw)
        return SpellCheckResponse(
            original_text=parsed.original_text,
            corrected_text=parsed.corrected_text,
            misspellings=parsed.suggestions,
        )

    async def rewrite(
        self, text: str, style: str, instructions: str | None = None
    ) -> RewriteResponse:
        """Rewrite text in the requested style while preserving its meaning."""
        prompt = (
            f"You are an editor. Rewrite the following text in a {style} style. "
            "Preserve the original meaning and the author's intent, and improve readability and flow. "
            "Do not add new information or change the subject."
        )
        if instructions:
            prompt += f" Additional instructions: {instructions}."
        prompt += (
            f"\n\nOriginal text:\n{text[:5000]}\n\n"
            "Return ONLY the rewritten text — no preamble, no quotation marks, no markdown."
        )

        rewritten = await self._generate(prompt, temperature=0.5)
        return RewriteResponse(original_text=text, rewritten_text=rewritten.strip(), style=style)

    async def status(self) -> AIStatusResponse:
        """Check if Ollama is running and the configured model is available."""
        global _last_status_check, _cached_status

        # Use cached status if fresh
        if _cached_status and _last_status_check:
            elapsed = (datetime.now(timezone.utc) - _last_status_check).total_seconds()
            if elapsed < _STATUS_CACHE_TTL_SECONDS:
                return _cached_status

        try:
            client = _get_client()
            # Availability probe is on every settings/AI panel render and gates
            # enrichment — never wait the generation timeout for it.
            response = await client.get(
                f"{self.base_url}/api/tags", timeout=_status_timeout()
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            model_loaded = any(self.model in m for m in models)

            result = AIStatusResponse(
                ollama_available=True,
                model_name=self.model,
                model_loaded=model_loaded,
                model_names=models,
                error=None
                if model_loaded
                else f"Model '{self.model}' not found. Available: {models}",
            )
        except Exception as exc:
            result = AIStatusResponse(
                ollama_available=False,
                model_name=self.model,
                model_loaded=False,
                model_names=[],
                error=f"Cannot connect to Ollama: {exc}",
            )

        _last_status_check = datetime.now(timezone.utc)
        _cached_status = result
        return result

    # ── Embeddings (semantic search) ────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Get a text embedding via the active provider — Ollama
        ``/api/embeddings`` by default, or an OpenAI-compatible ``/embeddings``
        when a cloud provider is active.

        Concurrent calls for the same text are single-flighted: N searches that
        land together share one in-flight request instead of stacking N
        identical embedding calls on a local model.
        """
        from app.services.ai_provider_service import get_active_provider

        provider = await get_active_provider()
        model = (
            provider.model
            if provider is not None and provider.preset != "ollama"
            else settings.OLLAMA_EMBED_MODEL
        )
        key = f"{model}\x00{text}"
        inflight = _embed_inflight.get(key)
        if inflight is not None and not inflight.done():
            return await inflight
        task = asyncio.create_task(self._embed_request(provider, text))
        _embed_inflight[key] = task
        try:
            return await task
        finally:
            if _embed_inflight.get(key) is task:
                _embed_inflight.pop(key, None)

    async def _embed_request(self, provider: Any, text: str) -> list[float]:
        """Perform the actual embedding HTTP call (see :meth:`embed`)."""
        try:
            if provider is not None and provider.preset != "ollama":
                api_key = (
                    security.decrypt(provider.api_key_encrypted)
                    if provider.api_key_encrypted
                    else None
                )
                return await self._embed_openai(
                    provider.base_url, api_key, provider.model, text, timeout=_embed_timeout()
                )
            base_url = provider.base_url if provider is not None else self.base_url
            client = _get_client()
            response = await client.post(
                f"{base_url}/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},
                timeout=_embed_timeout(),
            )
            response.raise_for_status()
            return list(response.json()["embedding"])
        except httpx.TimeoutException as exc:
            raise OllamaServiceError(
                f"Embedding model '{settings.OLLAMA_EMBED_MODEL}' took too long to respond "
                f"(timed out after {_embed_timeout():.0f}s)."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaServiceError(f"Cannot reach the embedding endpoint: {exc}") from exc

    async def _embed_openai(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        text: str,
        timeout: float | None = None,
    ) -> list[float]:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        client = _get_client()
        response = await client.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": text},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return list(response.json()["data"][0]["embedding"])

    # ── Combined analysis (sentiment + summary + prompts) ──────────────

    async def analyze_entry(self, text: str) -> dict[str, Any] | None:
        """Combined analysis: sentiment + summary + reflection prompts in one LLM call."""
        prompt = (
            "Analyze this journal entry. Return ONLY a valid JSON object with this exact structure:\n"
            '{"sentiment": {"primary_emotion": "...", "secondary_emotion": "...", '
            '"intensity": 5, "valence": 0.0}, '
            '"summary": "A 1-2 sentence summary of the entry.", '
            '"reflection_prompts": ["Question 1?", "Question 2?", "Question 3?"]}\n\n'
            "Guidelines:\n"
            "- primary_emotion: one of joy, sadness, anger, fear, surprise, disgust, neutral, anxiety, gratitude, hope, nostalgia, frustration, contentment, excitement\n"
            "- secondary_emotion: optional, same set\n"
            "- intensity: 1-10 (how strong the emotion is)\n"
            "- valence: -1.0 (very negative) to 1.0 (very positive)\n"
            "- summary: concise, capture the key point\n"
            "- reflection_prompts: 3 thought-provoking questions to help the writer reflect deeper\n\n"
            f"Entry:\n{text[:3000]}\n\n"
            "Return ONLY the raw JSON object — no markdown code fence, no commentary."
        )
        raw = await self._generate(prompt, temperature=0.3)
        result = self._parse_json_response(raw)
        if isinstance(result, dict):
            return result
        return None

    # ── Tag suggestions ────────────────────────────────────────────────

    async def suggest_tags(self, text: str, existing_tags: list[str]) -> list[str]:
        """Suggest relevant tags for a journal entry."""
        existing = ", ".join(existing_tags) if existing_tags else "none"
        prompt = (
            f"Given this journal entry, suggest 3-5 relevant tags.\n"
            f"Existing tags to reuse where appropriate: [{existing}]\n"
            f'Tags should be lowercase, use hyphens for multi-word (e.g. "work-life").\n'
            f'Return ONLY a raw JSON array of strings, e.g. ["tag1", "tag2", "tag3"], '
            f"with no markdown code fence or commentary.\n\n"
            f"Entry:\n{text[:2000]}"
        )
        raw = await self._generate(prompt, temperature=0.2)
        result = self._parse_json_response(raw)
        if isinstance(result, list):
            return [str(t).strip().lower() for t in result if t][:5]
        return []

    # ── Writer's block helper ──────────────────────────────────────────

    async def continue_writing(self, text: str) -> str:
        """Generate a short continuation suggestion for writer's block."""
        prompt = (
            "You are a thoughtful writing partner. Continue this journal entry with 1-3 sentences "
            "that naturally follow what is already written. Match the author's voice, tense, and point of view exactly. "
            "Do not repeat what is already there.\n\n"
            f"So far:\n{text[-1000:]}\n\n"
            "Return ONLY the continuation — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.7, num_predict=256)
        return result.strip()

    # ── Theme detection ────────────────────────────────────────────────

    async def detect_themes(self, summaries_by_month: dict[str, list[str]]) -> list[dict[str, Any]]:
        """Detect recurring themes across months of journal entries."""
        sections = []
        for month, summaries in summaries_by_month.items():
            sections.append(f"{month}: " + " | ".join(summaries[:10]))

        prompt = (
            "Analyze these monthly journal summaries and identify 3-5 recurring themes. "
            "Return ONLY a raw JSON array of objects — no markdown code fence, no commentary: "
            '[{"theme": "...", "frequency": "monthly|weekly|occasional", '
            '"months_mentioned": ["Jan 2026", ...], "insight": "Brief observation"}]\n\n'
            + "\n".join(sections[:20])
        )
        raw = await self._generate(prompt, temperature=0.3)
        result = self._parse_json_response(raw)
        if isinstance(result, list):
            return result[:5]
        return []

    # ── Shared JSON parser ─────────────────────────────────────────────

    async def expand(self, text: str) -> str:
        """Expand and elaborate on the given text."""
        prompt = (
            "You are an editor. Expand and elaborate on the following text, adding vivid detail, "
            "sensory description, and emotional depth. Preserve the author's voice, tense, and point of view; "
            "do not change the subject or introduce unrelated facts.\n\n"
            f"Text:\n{text[:2000]}\n\n"
            "Return ONLY the expanded text — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.7, num_predict=2048)
        return result.strip()

    async def change_tone(self, text: str, tone: str) -> str:
        """Rewrite text in a different tone."""
        prompt = (
            f"You are an editor. Rewrite the following text in a {tone} tone. "
            "Keep the same meaning and facts; adjust only the style, register, and word choice. "
            "Do not add or remove information.\n\n"
            f"Text:\n{text[:3000]}\n\n"
            "Return ONLY the rewritten text — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.5, num_predict=2048)
        return result.strip()

    async def analyze_text(self, text: str) -> dict[str, Any]:
        """Analyze text for emotions, themes, and a brief summary."""
        prompt = (
            "Analyze the following text and return ONLY a valid JSON object with this exact structure:\n"
            '{"emotions": ["emotion1", "emotion2", ...], '
            '"themes": ["theme1", "theme2", ...], '
            '"summary": "A brief 1-2 sentence summary."}\n\n'
            "Guidelines:\n"
            "- emotions: 2-5 emotions conveyed in the text (e.g. joy, sadness, anxiety, gratitude, frustration, hope, nostalgia)\n"
            "- themes: 2-4 key topics or themes present in the text\n"
            "- summary: a concise summary of what the text is about\n\n"
            f"Text:\n{text[:3000]}\n\n"
            "Return ONLY the raw JSON object — no markdown code fence, no commentary."
        )
        raw = await self._generate(prompt, temperature=0.3)
        result = self._parse_json_response(raw)
        if isinstance(result, dict):
            return result
        return {"emotions": [], "themes": [], "summary": "Analysis unavailable."}

    async def define_text(self, text: str) -> str:
        """Provide a definition or explanation of the given text (word, phrase, or concept)."""
        prompt = (
            "You are a lexicographer. Define or explain the following word, phrase, or concept clearly and concisely. "
            "Give the part of speech where useful, a plain-language definition, and a short usage example. "
            "Do not pad with unnecessary detail.\n\n"
            f"Term:\n{text[:1000]}\n\n"
            "Return ONLY the definition — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.3, num_predict=512)
        return result.strip()

    async def change_voice(self, text: str, voice: str) -> str:
        """Convert text between active and passive voice."""
        prompt = (
            f"You are an editor. Rewrite the following text entirely in the {voice} voice. "
            f"Keep the same meaning; convert every clause to {voice} voice and keep tense and actors consistent. "
            "Do not add commentary.\n\n"
            f"Text:\n{text[:3000]}\n\n"
            "Return ONLY the converted text — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.3, num_predict=2048)
        return result.strip()

    async def rewrite_for_clarity(self, text: str) -> str:
        """Rewrite text for maximum clarity and readability."""
        prompt = (
            "You are an editor. Rewrite the following text for maximum clarity and readability. "
            "Split long sentences, remove ambiguity, prefer concrete words, and improve flow. "
            "Preserve the original meaning, tone, and level of formality; do not add or omit information.\n\n"
            f"Text:\n{text[:3000]}\n\n"
            "Return ONLY the rewritten text — no preamble, no quotation marks, no markdown."
        )
        result = await self._generate(prompt, temperature=0.3, num_predict=2048)
        return result.strip()

    # ── Generic registry tools ───────────────────────────────────────────

    async def run_generic_tool(
        self, tool_id: str, text: str, param_value: str | None = None
    ) -> str:
        """Run a registry-defined text tool and return its plain-text result.

        Raises ``KeyError`` for an unknown ``tool_id`` and ``ValueError`` for an
        invalid parameter value (the router maps these to 404 / 400).
        """
        from app.services.ai_tool_registry import get_spec

        spec = get_spec(tool_id)
        if spec is None:
            raise KeyError(tool_id)

        value = param_value
        if spec.param is not None:
            allowed = spec.param.options
            value = param_value if param_value is not None else spec.param.default
            if value not in allowed:
                raise ValueError(
                    f"Invalid {spec.param.name!r} for tool {tool_id!r}: {value!r}. "
                    f"Allowed: {', '.join(allowed)}"
                )

        prompt = spec.prompt_builder(text, value)
        result = await self._generate(
            prompt, temperature=spec.temperature, num_predict=spec.num_predict
        )
        return result.strip()

    # ── Shared JSON parser (original) ─────────────────────────────────────

    def _parse_json_response(self, raw: str) -> dict[str, Any] | list[Any] | None:
        """Extract and parse JSON from LLM response text."""
        text = raw.strip()
        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            logger.debug("LLM response was not raw JSON; attempting boundary extraction")
        # Find JSON boundaries
        start = text.find("{")
        if start < 0:
            start = text.find("[")
        end = max(text.rfind("}"), text.rfind("]")) + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                logger.debug("Failed JSON boundary extraction for LLM response")
        logger.warning("Failed to parse JSON from LLM response: %s", text[:200])
        return None

    def _parse_grammar_response(self, original: str, raw: str) -> GrammarCheckResponse:
        """Parse Ollama's JSON response into structured grammar check result."""
        # Try to extract JSON from the response (may have surrounding text)
        text = raw.strip()
        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        try:
            data: dict[str, Any] = json.loads(text)
            raw_suggestions = data.get("suggestions") or data.get("misspellings") or []
            suggestions = [
                Suggestion(
                    offset=s.get("offset", 0),
                    length=s.get("length", 0),
                    original=s.get("original", ""),
                    suggestion=s.get("suggestion", ""),
                    rule_id=s.get("rule_id", "unknown"),
                    message=s.get("message", ""),
                )
                for s in raw_suggestions
            ]
            return GrammarCheckResponse(
                original_text=original,
                corrected_text=data.get("corrected_text", original),
                suggestions=suggestions,
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse Ollama grammar response: %s", exc)
            return GrammarCheckResponse(
                original_text=original, corrected_text=original, suggestions=[]
            )
