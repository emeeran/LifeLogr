"""AI assistance route handlers (Ollama-backed)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.digest import Digest
from app.models.entry import Entry
from app.models.reflection_prompt import EntryPrompt
from app.models.sentiment import EntrySentiment
from app.models.tag import Tag
from app.schemas.ai import (
    AIStatusResponse,
    ContinueWritingRequest,
    ContinueWritingResponse,
    DigestResponse,
    EntryAnalysisResponse,
    GrammarCheckRequest,
    GrammarCheckResponse,
    OnThisDayPastEntry,
    OnThisDayResponse,
    RewriteRequest,
    RewriteResponse,
    SentimentData,
    SimilarEntriesResponse,
    SimilarEntry,
    SpellCheckRequest,
    SpellCheckResponse,
    TagSuggestionRequest,
    TagSuggestionResponse,
    ThemesResponse,
    ThemeInsight,
)
from app.services.embedding_service import EmbeddingService
from app.services.ollama_service import OllamaService

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ── Existing features ──────────────────────────────────────────────────

@router.post("/grammar-check", response_model=GrammarCheckResponse)
async def grammar_check(data: GrammarCheckRequest, db: AsyncSession = Depends(get_db)) -> Any:
    svc = OllamaService()
    return await svc.grammar_check(data.text, data.language)


@router.post("/spell-check", response_model=SpellCheckResponse)
async def spell_check(data: SpellCheckRequest, db: AsyncSession = Depends(get_db)) -> Any:
    svc = OllamaService()
    return await svc.spell_check(data.text, data.language)


@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_text(data: RewriteRequest, db: AsyncSession = Depends(get_db)) -> Any:
    svc = OllamaService()
    return await svc.rewrite(data.text, data.style, data.instructions)


@router.get("/status", response_model=AIStatusResponse)
async def ai_status(db: AsyncSession = Depends(get_db)) -> Any:
    svc = OllamaService()
    status = await svc.status()
    # Check if embedding model is available
    embed_available = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                models = [m.get("name", "") for m in r.json().get("models", [])]
                embed_available = any(settings.OLLAMA_EMBED_MODEL in m for m in models)
    except Exception:
        pass
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


# ── Entry analysis ─────────────────────────────────────────────────────

@router.post("/entry-analysis/{entry_id}/run", response_model=EntryAnalysisResponse)
async def run_entry_analysis(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Trigger AI analysis on demand for a specific entry, then return results."""
    from fastapi import HTTPException

    result = await db.execute(select(Entry).where(Entry.id == entry_id, ~Entry.is_deleted))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    await _run_enrichment_sync(entry_id, entry.title, entry.body)
    return await _load_analysis(entry_id, db)


async def _run_enrichment_sync(entry_id: int, title: str | None, body: str) -> None:
    """Run enrichment synchronously (awaited) so results are available immediately."""
    ollama = OllamaService()
    status = await ollama.status()
    if not status.ollama_available:
        return

    text = f"{title or ''}\n\n{body}".strip()
    if not text.strip():
        return

    if settings.AI_ENABLE_SENTIMENT or settings.AI_ENABLE_SUMMARIZATION or settings.AI_ENABLE_REFLECTION_PROMPTS:
        from app.services.enrichment_service import _analyze_entry
        await _analyze_entry(entry_id, text, ollama)


async def _load_analysis(entry_id: int, db: AsyncSession) -> EntryAnalysisResponse:
    """Load existing analysis data for an entry."""
    sentiment = None
    summary = None
    prompts = []

    sent_result = await db.execute(
        select(EntrySentiment).where(EntrySentiment.entry_id == entry_id)
    )
    sent = sent_result.scalar_one_or_none()
    if sent:
        sentiment = SentimentData(
            primary_emotion=sent.primary_emotion,
            secondary_emotion=sent.secondary_emotion,
            intensity=sent.intensity,
            valence=sent.valence,
        )

    entry_result = await db.execute(
        select(Entry.summary).where(Entry.id == entry_id)
    )
    summary = entry_result.scalar_one_or_none()

    prompts_result = await db.execute(
        select(EntryPrompt.prompt_text).where(EntryPrompt.entry_id == entry_id)
    )
    prompts = [row[0] for row in prompts_result]

    return EntryAnalysisResponse(
        entry_id=entry_id,
        sentiment=sentiment,
        summary=summary,
        reflection_prompts=prompts,
    )


@router.get("/entry-analysis/{entry_id}", response_model=EntryAnalysisResponse)
async def get_entry_analysis(entry_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get the AI analysis (sentiment, summary, prompts) for an entry."""
    return await _load_analysis(entry_id, db)


# ── Similar entries ────────────────────────────────────────────────────

@router.get("/similar/{entry_id}", response_model=SimilarEntriesResponse)
async def find_similar(entry_id: int, top_k: int = Query(5, ge=1, le=20), db: AsyncSession = Depends(get_db)) -> Any:
    """Find entries similar to the given entry using embeddings."""
    svc = EmbeddingService(db)
    similar_ids = await svc.find_similar(entry_id, top_k)

    if not similar_ids:
        return SimilarEntriesResponse(entry_id=entry_id, similar=[])

    # Load entry details
    entries_result = await db.execute(
        select(Entry.id, Entry.entry_date, Entry.title)
        .where(Entry.id.in_([s[0] for s in similar_ids]))
    )
    entry_map = {row.id: row for row in entries_result}

    similar = []
    for eid, score in similar_ids:
        row = entry_map.get(eid)
        if row:
            similar.append(SimilarEntry(
                id=row.id,
                entry_date=row.entry_date,
                title=row.title,
                similarity_score=round(score, 4),
            ))

    return SimilarEntriesResponse(entry_id=entry_id, similar=similar)


# ── Writer's block helper ──────────────────────────────────────────────

@router.post("/continue-writing", response_model=ContinueWritingResponse)
async def continue_writing(data: ContinueWritingRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Generate a short continuation suggestion."""
    svc = OllamaService()
    continuation = await svc.continue_writing(data.text)
    return ContinueWritingResponse(continuation=continuation)


# ── On this day ────────────────────────────────────────────────────────

@router.get("/on-this-day", response_model=OnThisDayResponse)
async def on_this_day(db: AsyncSession = Depends(get_db)) -> Any:
    """Generate an AI reflection on entries from this date in past years."""
    today = date.today()
    past_entries: list[dict[str, Any]] = []

    for years_ago in range(1, 6):
        past_date = today.replace(year=today.year - years_ago)
        result = await db.execute(
            select(Entry).where(
                ~Entry.is_deleted,
                Entry.entry_date == past_date,
            )
        )
        entries = list(result.scalars().all())
        if entries:
            text = "\n\n".join(f"**{e.title or 'Untitled'}** ({years_ago} years ago)\n{e.body[:500]}" for e in entries)
            first = entries[0]
            past_entries.append({
                "years_ago": years_ago,
                "date": str(past_date),
                "title": first.title,
                "snippet": (first.body[:150].strip() + "...") if len(first.body) > 150 else first.body.strip(),
                "text": text,
            })

    if not past_entries:
        return OnThisDayResponse(
            years_ago=0, entries_count=0,
            reflection="No entries found on this date in previous years.",
            past_entries=[],
        )

    # Combine all past entries and generate reflection
    combined = "\n\n---\n\n".join(p["text"] for p in past_entries)
    closest = past_entries[0]
    svc = OllamaService()
    reflection = await svc.reflect_on_past(combined, closest["years_ago"])

    return OnThisDayResponse(
        years_ago=int(closest["years_ago"]),
        entries_count=len(past_entries),
        reflection=reflection,
        past_entries=[
            OnThisDayPastEntry(
                years_ago=int(p["years_ago"]),
                date=str(p["date"]),
                title=p["title"] if isinstance(p["title"], str) else None,
                snippet=p["snippet"] if isinstance(p["snippet"], str) else None,
            )
            for p in past_entries
        ],
    )


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
        .where(~Entry.is_deleted, Entry.summary.is_not(None), Entry.entry_date >= cutoff)
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


# ── Weekly digest ──────────────────────────────────────────────────────

@router.get("/digests", response_model=list[DigestResponse])
async def list_digests(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List past weekly digests."""
    result = await db.execute(
        select(Digest).order_by(Digest.week_start.desc()).limit(limit)
    )
    digests = list(result.scalars().all())
    return [
        DigestResponse(
            id=d.id,
            week_start=d.week_start,
            week_end=d.week_end,
            themes=json.loads(d.themes) if d.themes else [],
            emotional_trajectory=d.emotional_trajectory,
            notable_moments=json.loads(d.notable_moments) if d.notable_moments else [],
            summary_text=d.summary_text,
            created_at=d.created_at,
        )
        for d in digests
    ]


@router.get("/digests/latest", response_model=DigestResponse | None)
async def latest_digest(db: AsyncSession = Depends(get_db)) -> Any:
    """Get the most recent weekly digest."""
    result = await db.execute(
        select(Digest).order_by(Digest.week_start.desc()).limit(1)
    )
    d = result.scalar_one_or_none()
    if not d:
        return None
    return DigestResponse(
        id=d.id,
        week_start=d.week_start,
        week_end=d.week_end,
        themes=json.loads(d.themes) if d.themes else [],
        emotional_trajectory=d.emotional_trajectory,
        notable_moments=json.loads(d.notable_moments) if d.notable_moments else [],
        summary_text=d.summary_text,
        created_at=d.created_at,
    )


@router.post("/digests/generate", response_model=DigestResponse)
async def generate_digest(db: AsyncSession = Depends(get_db)) -> Any:
    """Generate a digest for the current week on demand."""
    from fastapi import HTTPException

    from app.services.digest_service import DigestService
    svc = DigestService(db)
    try:
        digest = await svc.generate_for_week(date.today() - timedelta(days=date.today().weekday()))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return DigestResponse(
        id=digest.id,
        week_start=digest.week_start,
        week_end=digest.week_end,
        themes=json.loads(digest.themes) if digest.themes else [],
        emotional_trajectory=digest.emotional_trajectory,
        notable_moments=json.loads(digest.notable_moments) if digest.notable_moments else [],
        summary_text=digest.summary_text,
        created_at=digest.created_at,
    )


# ── Model management ───────────────────────────────────────────────────

@router.post("/pull-model")
async def pull_model(model: str = Query(..., description="Model name to pull (e.g. nomic-embed-text)")) -> Any:
    """Trigger pulling an Ollama model. Returns immediately; pull runs in background."""
    import asyncio

    async def _pull() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama", "pull", model,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to pull model %s: %s", model, e)

    asyncio.create_task(_pull())
    return {"status": "pulling", "model": model}
