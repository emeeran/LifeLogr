"""AI assistance route handlers (Ollama-backed)."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entry import Entry
from app.models.tag import Tag
from app.schemas.ai import (
    AIStatusResponse,
    AnalyzeTextRequest,
    AnalyzeTextResponse,
    ChangeToneRequest,
    ChangeToneResponse,
    ContinueWritingRequest,
    ContinueWritingResponse,
    DefineTextRequest,
    DefineTextResponse,
    ExpandRequest,
    ExpandResponse,
    GenericToolRequest,
    GenericToolResponse,
    GrammarCheckRequest,
    GrammarCheckResponse,
    RewriteRequest,
    RewriteResponse,
    RewriteForClarityRequest,
    RewriteForClarityResponse,
    SpellCheckRequest,
    SpellCheckResponse,
    TagSuggestionRequest,
    TagSuggestionResponse,
    ThemesResponse,
    ThemeInsight,
    VoiceChangeRequest,
    VoiceChangeResponse,
)
from app.services.ollama_service import OllamaService
from app.core import security
from app.models.ai_provider import AIProvider
from app.schemas.ai_provider import (
    AIProviderCreate,
    AIProviderResponse,
    AIProviderUpdate,
    ProviderModelsRequest,
)
from app.services.ai_provider_service import (
    AIProviderService,
    PROVIDER_PRESETS,
    list_models,
    test_connection,
)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
logger = logging.getLogger(__name__)


# ── Existing features ──────────────────────────────────────────────────


@router.post("/grammar-check", response_model=GrammarCheckResponse)
async def grammar_check(data: GrammarCheckRequest) -> Any:
    svc = OllamaService()
    return await svc.grammar_check(data.text, data.language)


@router.post("/spell-check", response_model=SpellCheckResponse)
async def spell_check(data: SpellCheckRequest) -> Any:
    svc = OllamaService()
    return await svc.spell_check(data.text, data.language)


@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_text(data: RewriteRequest) -> Any:
    svc = OllamaService()
    return await svc.rewrite(data.text, data.style, data.instructions)


@router.get("/status", response_model=AIStatusResponse)
async def ai_status() -> Any:
    svc = OllamaService()
    status = await svc.status()
    # Check if embedding model is available using same status call
    embed_available = (
        any(settings.OLLAMA_EMBED_MODEL in m for m in status.model_names)
        if status.ollama_available
        else False
    )
    return AIStatusResponse(
        ollama_available=status.ollama_available,
        model_name=status.model_name,
        model_loaded=status.model_loaded,
        embed_model_available=embed_available,
        error=status.error,
    )


# ── Tag suggestions ────────────────────────────────────────────────────


@router.post("/suggest-tags", response_model=TagSuggestionResponse)
async def suggest_tags(data: TagSuggestionRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Suggest tags for a journal entry based on its content."""
    # Load existing tag names
    result = await db.execute(select(Tag.name))
    existing = [row[0] for row in result]
    svc = OllamaService()
    tags = await svc.suggest_tags(data.text, existing)
    return TagSuggestionResponse(tags=tags)


# ── Writer's block helper ──────────────────────────────────────────────


@router.post("/continue-writing", response_model=ContinueWritingResponse)
async def continue_writing(data: ContinueWritingRequest) -> Any:
    """Generate a short continuation suggestion."""
    svc = OllamaService()
    continuation = await svc.continue_writing(data.text)
    return ContinueWritingResponse(continuation=continuation)


# ── Theme detection ────────────────────────────────────────────────────


@router.get("/themes", response_model=ThemesResponse)
async def detect_themes(
    months: int = Query(6, ge=1, le=24, description="Number of months to analyze"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Detect recurring themes across recent journal entries."""
    # Load summaries grouped by month
    cutoff = date.today() - timedelta(days=months * 30)
    result = await db.execute(
        select(
            func.strftime("%Y-%m", Entry.entry_date).label("month"),
            Entry.summary,
        )
        .where(
            ~Entry.is_deleted,
            ~Entry.is_encrypted,
            Entry.summary.is_not(None),
            Entry.entry_date >= cutoff,
        )
        .order_by(Entry.entry_date)
    )

    summaries_by_month: dict[str, list[str]] = {}
    for row in result:
        if row.month not in summaries_by_month:
            summaries_by_month[row.month] = []
        if row.summary:
            summaries_by_month[row.month].append(row.summary)

    if not summaries_by_month:
        return ThemesResponse(themes=[])

    svc = OllamaService()
    themes = await svc.detect_themes(summaries_by_month)
    return ThemesResponse(themes=[ThemeInsight(**t) if isinstance(t, dict) else t for t in themes])


# ── Smart Tools ────────────────────────────────────────────────────────


@router.post("/expand", response_model=ExpandResponse)
async def expand_text(data: ExpandRequest) -> Any:
    """Expand and elaborate on text."""
    svc = OllamaService()
    expanded = await svc.expand(data.text)
    return ExpandResponse(expanded_text=expanded)


@router.post("/change-tone", response_model=ChangeToneResponse)
async def change_tone(data: ChangeToneRequest) -> Any:
    """Change the tone of text."""
    svc = OllamaService()
    changed = await svc.change_tone(data.text, data.tone)
    return ChangeToneResponse(changed_text=changed, tone=data.tone)


@router.post("/analyze-text", response_model=AnalyzeTextResponse)
async def analyze_text(data: AnalyzeTextRequest) -> Any:
    """Analyze text for emotions, themes, and a brief summary."""
    svc = OllamaService()
    result = await svc.analyze_text(data.text)
    return AnalyzeTextResponse(
        emotions=result.get("emotions", []),
        themes=result.get("themes", []),
        summary=result.get("summary", ""),
    )


@router.post("/define-text", response_model=DefineTextResponse)
async def define_text(data: DefineTextRequest) -> Any:
    """Define or explain a word, phrase, or concept."""
    svc = OllamaService()
    definition = await svc.define_text(data.text)
    return DefineTextResponse(definition=definition)


@router.post("/change-voice", response_model=VoiceChangeResponse)
async def change_voice(data: VoiceChangeRequest) -> Any:
    """Convert text between active and passive voice."""
    svc = OllamaService()
    changed = await svc.change_voice(data.text, data.voice)
    return VoiceChangeResponse(changed_text=changed, voice=data.voice)


@router.post("/rewrite-for-clarity", response_model=RewriteForClarityResponse)
async def rewrite_for_clarity(data: RewriteForClarityRequest) -> Any:
    """Rewrite text for maximum clarity and readability."""
    svc = OllamaService()
    rewritten = await svc.rewrite_for_clarity(data.text)
    return RewriteForClarityResponse(rewritten_text=rewritten)


# ── Generic registry tools ─────────────────────────────────────────────


@router.post("/tool/{tool_id}", response_model=GenericToolResponse)
async def run_generic_tool(
    tool_id: str,
    data: GenericToolRequest,
) -> Any:
    """Run a registry-defined AI text tool (summarize, translate, …)."""
    svc = OllamaService()
    try:
        result = await svc.run_generic_tool(tool_id, data.text, data.param)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown AI tool: {tool_id}") from None
    except ValueError as exc:
        logger.warning("Invalid AI tool parameter for %s: %s", tool_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenericToolResponse(result=result)


# ── Model management ───────────────────────────────────────────────────


@router.post("/pull-model")
async def pull_model(
    model: str = Query(..., description="Model name to pull (e.g. nomic-embed-text)"),
) -> Any:
    """Trigger pulling an Ollama model. Returns immediately; pull runs in background."""
    import asyncio
    import re

    # Validate model name to prevent command injection
    if not re.match(r"^[a-zA-Z0-9._:/-]+$", model):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Invalid model name. Use alphanumeric characters, dots, hyphens, colons, and slashes only.",
        )

    async def _pull() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama",
                "pull",
                model,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            import logging

            logging.getLogger(__name__).error("Failed to pull model %s: %s", model, e)

    asyncio.create_task(_pull())
    return {"status": "pulling", "model": model}


# ── AI providers (OpenAI-compatible cloud + local Ollama) ────────────────────
def _to_provider_response(p: AIProvider) -> AIProviderResponse:
    return AIProviderResponse(
        id=p.id,
        name=p.name,
        preset=p.preset,
        base_url=p.base_url,
        model=p.model,
        has_key=p.api_key_encrypted is not None,
        is_active=p.is_active,
        created_at=p.created_at,
    )


def _provider_http_error(exc: Exception) -> HTTPException:
    """Map an httpx failure to a 502 carrying the provider's own error body.

    Providers return actionable JSON on auth/model failures (e.g. Gemini's 401
    body is literally ``"API key not valid. Please pass a valid API key."``).
    Surfacing it — instead of a bare ``Client error '401 Unauthorized'`` — tells
    the user exactly what's wrong. Used by both the Test and List-models routes.
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        body = exc.response.text[:300]
        return HTTPException(
            status_code=502,
            detail=f"Provider returned HTTP {exc.response.status_code}: {body}",
        )
    return HTTPException(status_code=502, detail=f"Connection failed: {exc}")


@router.get("/providers/presets")
async def provider_presets() -> list[dict[str, str]]:
    """The provider preset catalogue (key → label/base_url/default model)."""
    return [
        {"key": k, "label": v["label"], "base_url": v["base_url"], "model": v["model"]}
        for k, v in PROVIDER_PRESETS.items()
    ]


@router.get("/providers", response_model=list[AIProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)) -> Any:
    return [_to_provider_response(p) for p in await AIProviderService(db).list()]


@router.post("/providers", response_model=AIProviderResponse, status_code=201)
async def create_provider(data: AIProviderCreate, db: AsyncSession = Depends(get_db)) -> Any:
    return _to_provider_response(await AIProviderService(db).create(data))


@router.patch("/providers/{provider_id}", response_model=AIProviderResponse)
async def update_provider(
    provider_id: int, data: AIProviderUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    try:
        return _to_provider_response(await AIProviderService(db).update(provider_id, data))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)) -> None:
    try:
        await AIProviderService(db).delete(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/providers/{provider_id}/activate", response_model=AIProviderResponse)
async def activate_provider(provider_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        return _to_provider_response(await AIProviderService(db).activate(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Probe the provider with a 1-token completion to verify the key/endpoint."""
    svc = AIProviderService(db)
    try:
        provider = await svc._get(provider_id)  # noqa: SLF001
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    api_key = security.decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else None
    try:
        model = await test_connection(provider.base_url, api_key, provider.model)
    except Exception as exc:  # httpx errors, etc.
        raise _provider_http_error(exc) from exc
    return {"status": "ok", "model": model}


@router.get("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """List the models the provider exposes (drives the model selector in the UI)."""
    svc = AIProviderService(db)
    try:
        provider = await svc._get(provider_id)  # noqa: SLF001
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    api_key = security.decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else None
    try:
        models = await list_models(provider.base_url, api_key)
    except Exception as exc:  # httpx errors, etc.
        raise _provider_http_error(exc) from exc
    return {"models": models}


@router.post("/providers/models")
async def preview_provider_models(data: ProviderModelsRequest) -> dict[str, Any]:
    """List models from an arbitrary base_url + key (Add form, pre-save).

    Mirrors ``GET /providers/{id}/models`` but takes the endpoint + key directly
    so the Add form can browse a provider's models before it is created.
    """
    try:
        models = await list_models(data.base_url, data.api_key)
    except Exception as exc:  # httpx errors, etc.
        raise _provider_http_error(exc) from exc
    return {"models": models}
