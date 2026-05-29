"""Ollama API client for AI text assistance, embeddings, and analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.schemas.ai import (
    AIStatusResponse,
    GrammarCheckResponse,
    RewriteResponse,
    SpellCheckResponse,
    Suggestion,
)

logger = logging.getLogger(__name__)

# Cache for model availability check
_last_status_check: datetime | None = None
_cached_status: AIStatusResponse | None = None
_STATUS_CACHE_TTL_SECONDS = 60


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
        """Send a generate request to Ollama and return the response text."""
        import httpx

        options: dict[str, Any] = {"num_predict": num_predict}
        if temperature is not None:
            options["temperature"] = temperature

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model or self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return str(data.get("response", ""))

    async def grammar_check(self, text: str, language: str = "en") -> GrammarCheckResponse:
        """Check grammar and spelling, returning suggestions and corrected text."""
        prompt = (
            f"You are a grammar and spelling checker for {language} text. "
            f"Analyze the following text and return a JSON object with this exact structure:\n"
            f'{{"corrected_text": "...", "suggestions": [{{"offset": 0, "length": 0, '
            f'"original": "...", "suggestion": "...", "rule_id": "...", "message": "..."}}]}}\n\n'
            f"Text to check:\n{text}\n\n"
            f"Return ONLY the JSON object, no other text."
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
            f"Return ONLY the JSON object."
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
        """Rewrite text for clarity and conciseness in a professional tone."""
        prompt = (
            "Rewrite the following text for clarity and conciseness in a professional tone. "
            "Preserve the core meaning while improving readability and flow."
        )
        if instructions:
            prompt += f" Additional instructions: {instructions}"
        prompt += f"\n\nOriginal text:\n{text}\n\nReturn ONLY the rewritten text, nothing else."

        rewritten = await self._generate(prompt)
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
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
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
        """Get text embedding via Ollama /api/embeddings."""
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},
            )
            response.raise_for_status()
            return list(response.json()["embedding"])

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
            f"Entry:\n{text[:3000]}"
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
            f'Return ONLY a JSON array of strings, e.g. ["tag1", "tag2", "tag3"]\n\n'
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
            "Continue this journal entry with 1-3 sentences that naturally follow. "
            "Write in the same voice and style. Return ONLY the continuation text, nothing else.\n\n"
            f"So far:\n{text[-1000:]}"
        )
        result = await self._generate(prompt, temperature=0.7, num_predict=256)
        return result.strip()

    # ── On this day reflection ─────────────────────────────────────────

    async def reflect_on_past(self, entries_text: str, years_ago: int) -> str:
        """Generate a warm reflection on past entries from the same date."""
        prompt = (
            f"Look at these journal entries written {years_ago} year(s) ago. "
            f"Write a brief, warm reflection (2-3 sentences) about what the person was experiencing "
            f"and how they might have grown since then. Be thoughtful and encouraging.\n\n"
            f"Past entries:\n{entries_text[:2000]}"
        )
        result = await self._generate(prompt, temperature=0.6)
        return result.strip()

    # ── Theme detection ────────────────────────────────────────────────

    async def detect_themes(self, summaries_by_month: dict[str, list[str]]) -> list[dict[str, Any]]:
        """Detect recurring themes across months of journal entries."""
        sections = []
        for month, summaries in summaries_by_month.items():
            sections.append(f"{month}: " + " | ".join(summaries[:10]))

        prompt = (
            "Analyze these monthly journal summaries and identify 3-5 recurring themes. "
            'Return ONLY a JSON array of objects: [{"theme": "...", "frequency": "monthly|weekly|occasional", '
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
            "Expand and elaborate on the following text, adding more detail, sensory descriptions, "
            "and emotional depth while maintaining the same voice and style. "
            "Return ONLY the expanded text, nothing else.\n\n"
            f"Text:\n{text[:2000]}"
        )
        result = await self._generate(prompt, temperature=0.7, num_predict=2048)
        return result.strip()

    async def change_tone(self, text: str, tone: str) -> str:
        """Rewrite text in a different tone."""
        prompt = (
            f"Rewrite the following text in a {tone} tone. "
            f"Keep the same meaning and content but adjust the style and word choice. "
            f"Return ONLY the rewritten text, nothing else.\n\n"
            f"Text:\n{text[:3000]}"
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
            f"Text:\n{text[:3000]}"
        )
        raw = await self._generate(prompt, temperature=0.3)
        result = self._parse_json_response(raw)
        if isinstance(result, dict):
            return result
        return {"emotions": [], "themes": [], "summary": "Analysis unavailable."}

    async def define_text(self, text: str) -> str:
        """Provide a definition or explanation of the given text (word, phrase, or concept)."""
        prompt = (
            "Define or explain the following word, phrase, or concept. "
            "Provide a clear, concise definition followed by usage examples if helpful. "
            "Return ONLY the definition text, nothing else.\n\n"
            f"Text:\n{text[:1000]}"
        )
        result = await self._generate(prompt, temperature=0.3, num_predict=512)
        return result.strip()

    # ── Shared JSON parser (original) ─────────────────────────────────────

    def _parse_json_response(self, raw: str) -> dict[str, Any] | list[Any] | None:
        """Extract and parse JSON from LLM response text."""
        text = raw.strip()
        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
        # Find JSON boundaries
        start = text.find("{")
        if start < 0:
            start = text.find("[")
        end = max(text.rfind("}"), text.rfind("]")) + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass
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
