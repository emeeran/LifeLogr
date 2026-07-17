"""Post-save AI enrichment pipeline — runs embedding + analysis asynchronously."""

from __future__ import annotations

import asyncio
import json
import logging


from app.core.config import settings
from app.core.database import async_session
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# Track pending enrichment tasks for graceful shutdown
_pending_tasks: set[asyncio.Task[None]] = set()


class EnrichmentService:
    """Orchestrates background AI tasks after an entry is saved."""

    @staticmethod
    def schedule(entry_id: int, title: str | None, body: str) -> None:
        """Fire-and-forget enrichment. Does not block the save response."""
        task = asyncio.create_task(_run_enrichment(entry_id, title, body))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)


async def cancel_pending_tasks() -> None:
    """Cancel all outstanding enrichment tasks (for graceful shutdown)."""
    for task in _pending_tasks:
        task.cancel()
    if _pending_tasks:
        await asyncio.gather(*_pending_tasks, return_exceptions=True)
    _pending_tasks.clear()


async def _run_enrichment(entry_id: int, title: str | None, body: str) -> None:
    """Run all enabled AI enrichment tasks for an entry."""
    try:
        ollama = OllamaService()
        status = await ollama.status()
        if not status.ollama_available:
            return

        text = f"{title or ''}\n\n{body}".strip()
        if not text.strip():
            return

        tasks = []

        if settings.AI_ENABLE_EMBEDDINGS:
            tasks.append(_generate_embedding(entry_id, text, ollama))

        if (
            settings.AI_ENABLE_SENTIMENT
            or settings.AI_ENABLE_SUMMARIZATION
            or settings.AI_ENABLE_REFLECTION_PROMPTS
        ):
            tasks.append(_analyze_entry(entry_id, text, ollama))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    except Exception:
        logger.exception("Enrichment failed for entry %d", entry_id)


async def _generate_embedding(entry_id: int, text: str, ollama: OllamaService) -> None:
    """Generate and store text embedding for semantic search."""
    try:
        from app.models.embedding import EntryEmbedding

        embedding_vec = await ollama.embed(text)
        embedding_json = json.dumps(embedding_vec)

        async with async_session() as session:
            # Upsert: delete existing, insert new
            await session.execute(
                EntryEmbedding.__table__.delete().where(EntryEmbedding.entry_id == entry_id)  # type: ignore[attr-defined]
            )
            session.add(
                EntryEmbedding(
                    entry_id=entry_id,
                    embedding=embedding_json,
                    model_name=settings.OLLAMA_EMBED_MODEL,
                )
            )
            await session.commit()
        # Keep the in-memory vector cache in sync (best-effort; the per-search
        # count check reloads on any divergence regardless).
        try:
            from app.services.semantic_cache import get_semantic_cache

            get_semantic_cache().update_entry(entry_id, embedding_vec)
        except Exception:
            logger.warning("Failed to update semantic cache for entry %d", entry_id, exc_info=True)
        logger.info("Embedding stored for entry %d (%d dims)", entry_id, len(embedding_vec))

    except Exception:
        logger.exception("Embedding generation failed for entry %d", entry_id)


async def _analyze_entry(entry_id: int, text: str, ollama: OllamaService) -> None:
    """Run combined sentiment + summary + prompts analysis."""
    try:
        analysis = await ollama.analyze_entry(text)
        if not analysis:
            return

        async with async_session() as session:
            # Store sentiment
            if settings.AI_ENABLE_SENTIMENT and "sentiment" in analysis:
                from app.models.sentiment import EntrySentiment

                sent = analysis["sentiment"]
                await session.execute(
                    EntrySentiment.__table__.delete().where(EntrySentiment.entry_id == entry_id)  # type: ignore[attr-defined]
                )
                session.add(
                    EntrySentiment(
                        entry_id=entry_id,
                        primary_emotion=sent.get("primary_emotion", "neutral"),
                        secondary_emotion=sent.get("secondary_emotion"),
                        intensity=sent.get("intensity", 5),
                        valence=sent.get("valence", 0.0),
                    )
                )

            # Store summary on entry row
            if settings.AI_ENABLE_SUMMARIZATION and "summary" in analysis:
                from app.models.entry import Entry

                summary = analysis["summary"][:500] if analysis["summary"] else None
                await session.execute(
                    Entry.__table__.update()  # type: ignore[attr-defined]
                    .where(Entry.id == entry_id)
                    .values(summary=summary)
                )

            # Store reflection prompts
            if settings.AI_ENABLE_REFLECTION_PROMPTS and "reflection_prompts" in analysis:
                from app.models.reflection_prompt import EntryPrompt

                await session.execute(
                    EntryPrompt.__table__.delete().where(EntryPrompt.entry_id == entry_id)  # type: ignore[attr-defined]
                )
                for prompt_text in analysis.get("reflection_prompts", [])[:5]:
                    if prompt_text and prompt_text.strip():
                        session.add(
                            EntryPrompt(
                                entry_id=entry_id,
                                prompt_text=prompt_text.strip()[:500],
                            )
                        )

            await session.commit()
        logger.info("Analysis stored for entry %d", entry_id)

    except Exception:
        logger.exception("Analysis failed for entry %d", entry_id)
