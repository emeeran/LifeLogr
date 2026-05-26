"""AI assistance route handlers (Ollama-backed)."""

from __future__ import annotations

import json
import logging
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
    ChangeToneRequest,
    ChangeToneResponse,
    ContinueWritingRequest,
    ContinueWritingResponse,
    DigestResponse,
    EntryAnalysisResponse,
    ExpandRequest,
    ExpandResponse,
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
    SummarizeRequest,
    SummarizeResponse,
    TagSuggestionRequest,
    TagSuggestionResponse,
    ThemesResponse,
    ThemeInsight,
    TranslateRequest,
    TranslateResponse,
)
from app.services.embedding_service import EmbeddingService
from app.services.ollama_service import OllamaService

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
logger = logging.getLogger(__name__)


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

    if (
        settings.AI_ENABLE_SENTIMENT
        or settings.AI_ENABLE_SUMMARIZATION
        or settings.AI_ENABLE_REFLECTION_PROMPTS
    ):
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

    entry_result = await db.execute(select(Entry.summary).where(Entry.id == entry_id))
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
async def find_similar(
    entry_id: int, top_k: int = Query(5, ge=1, le=20), db: AsyncSession = Depends(get_db)
) -> Any:
    """Find entries similar to the given entry using embeddings."""
    svc = EmbeddingService(db)
    similar_ids = await svc.find_similar(entry_id, top_k)

    if not similar_ids:
        return SimilarEntriesResponse(entry_id=entry_id, similar=[])

    # Load entry details
    entries_result = await db.execute(
        select(Entry.id, Entry.entry_date, Entry.title).where(
            Entry.id.in_([s[0] for s in similar_ids])
        )
    )
    entry_map = {row.id: row for row in entries_result}

    similar = []
    for eid, score in similar_ids:
        row = entry_map.get(eid)
        if row:
            similar.append(
                SimilarEntry(
                    id=row.id,
                    entry_date=row.entry_date,
                    title=row.title,
                    similarity_score=round(score, 4),
                )
            )

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
    try:
        today = date.today()
        # Handle Feb 29 on non-leap years by falling back to Feb 28
        past_dates: list[date] = []
        for y in range(1, 6):
            try:
                past_dates.append(today.replace(year=today.year - y))
            except ValueError:
                past_dates.append(today.replace(month=2, day=28, year=today.year - y))

        # Single query for all past dates instead of 5 separate queries
        result = await db.execute(
            select(Entry).where(
                ~Entry.is_deleted,
                Entry.entry_date.in_(past_dates),
            )
        )
        all_entries = result.scalars().all()

        # Group entries by year offset
        past_entries: list[dict[str, Any]] = []
        for years_ago, past_date in zip(range(1, 6), past_dates):
            date_entries = [e for e in all_entries if e.entry_date == past_date]
            if date_entries:
                text = "\n\n".join(
                    f"**{e.title or 'Untitled'}** ({years_ago} years ago)\n{e.body[:500]}"
                    for e in date_entries
                )
                first = date_entries[0]
                past_entries.append(
                    {
                        "years_ago": years_ago,
                        "date": str(past_date),
                        "title": first.title,
                        "snippet": (first.body[:150].strip() + "...")
                        if len(first.body) > 150
                        else first.body.strip(),
                        "text": text,
                        "entry_ids": [e.id for e in date_entries],
                    }
                )

        if not past_entries:
            return OnThisDayResponse(
                years_ago=0,
                entries_count=0,
                reflection="No entries found on this date in previous years.",
                past_entries=[],
            )

        # Combine all past entries and generate reflection
        combined = "\n\n---\n\n".join(p["text"] for p in past_entries)
        closest = past_entries[0]
        reflection = "No AI reflection available."
        try:
            svc = OllamaService()
            status = await svc.status()
            if status.ollama_available:
                reflection = await svc.reflect_on_past(combined, closest["years_ago"])
        except Exception:
            logger.warning("Ollama unavailable for on-this-day reflection", exc_info=True)

        return OnThisDayResponse(
            years_ago=closest["years_ago"],
            entries_count=len(past_entries),
            reflection=reflection,
            past_entries=[
                OnThisDayPastEntry(
                    years_ago=p["years_ago"],
                    date=str(p["date"]),
                    title=p["title"],
                    snippet=p["snippet"],
                    entry_ids=p.get("entry_ids", []),
                )
                for p in past_entries
            ],
        )
    except Exception:
        logger.error("On-this-day endpoint failed", exc_info=True)
        return OnThisDayResponse(
            years_ago=0,
            entries_count=0,
            reflection="Could not load on-this-day data. Please try again later.",
            past_entries=[],
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


def _digest_to_response(d: Digest) -> DigestResponse:
    """Convert a Digest ORM object to a DigestResponse schema."""
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


@router.get("/digests", response_model=list[DigestResponse])
async def list_digests(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List past weekly digests."""
    result = await db.execute(select(Digest).order_by(Digest.week_start.desc()).limit(limit))
    digests = list(result.scalars().all())
    return [_digest_to_response(d) for d in digests]


@router.get("/digests/latest", response_model=DigestResponse | None)
async def latest_digest(db: AsyncSession = Depends(get_db)) -> Any:
    """Get the most recent weekly digest."""
    result = await db.execute(select(Digest).order_by(Digest.week_start.desc()).limit(1))
    d = result.scalar_one_or_none()
    if not d:
        return None
    return _digest_to_response(d)


@router.post("/digests/generate", response_model=DigestResponse)
async def generate_digest(db: AsyncSession = Depends(get_db)) -> Any:
    """Generate a digest for the current week (or most recent week with entries)."""
    from fastapi import HTTPException

    from app.services.digest_service import DigestService

    svc = DigestService(db)
    # Try current week first, then walk back up to 4 weeks
    for weeks_ago in range(5):
        start = date.today() - timedelta(days=date.today().weekday() + weeks_ago * 7)
        try:
            digest = await svc.generate_for_week(start)
            return _digest_to_response(digest)
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail="No entries found in the last 5 weeks")


# ── Smart Tools ────────────────────────────────────────────────────────


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_text(data: SummarizeRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Summarize text concisely."""
    svc = OllamaService()
    summary = await svc.summarize(data.text)
    return SummarizeResponse(summary=summary)


@router.post("/expand", response_model=ExpandResponse)
async def expand_text(data: ExpandRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Expand and elaborate on text."""
    svc = OllamaService()
    expanded = await svc.expand(data.text)
    return ExpandResponse(expanded_text=expanded)


@router.post("/change-tone", response_model=ChangeToneResponse)
async def change_tone(data: ChangeToneRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Change the tone of text."""
    svc = OllamaService()
    changed = await svc.change_tone(data.text, data.tone)
    return ChangeToneResponse(changed_text=changed, tone=data.tone)


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(data: TranslateRequest, db: AsyncSession = Depends(get_db)) -> Any:
    """Translate text to another language."""
    svc = OllamaService()
    translated = await svc.translate(data.text, data.language)
    return TranslateResponse(translated_text=translated, language=data.language)


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
