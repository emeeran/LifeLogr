"""Post-save AI enrichment pipeline — runs embedding + analysis asynchronously."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from sqlalchemy import select

from app.core.config import settings
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# Track pending enrichment tasks for graceful shutdown
_pending_tasks: set[asyncio.Task[None]] = set()


# ── Concurrency cap ──────────────────────────────────────────────────────────
# ``schedule()`` is fire-and-forget, so a bulk import of N rows used to start N
# simultaneous Ollama jobs at once. A local model serves them serially anyway,
# so all that bought was N concurrent HTTP requests piling up on the event
# loop, the shared client and the user's machine. The semaphore below bounds
# how many enrichment jobs talk to the LLM at the same time.
_CONCURRENCY_ENV_VAR = "LIFEOGRF_ENRICHMENT_CONCURRENCY"
_CONCURRENCY_DEFAULT = 3
_semaphore: asyncio.Semaphore | None = None
_semaphore_cap = 0
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def enrichment_concurrency() -> int:
    """Configured cap on simultaneous enrichment jobs (always >= 1).

    Read from the environment rather than from
    :class:`~app.core.config.Settings` so the knob needs no config-schema
    change; the ``LIFEOGRF_`` prefix matches the existing alias convention
    (e.g. ``LIFEOGRF_API_TOKEN``).
    """
    raw = (os.environ.get(_CONCURRENCY_ENV_VAR) or "").strip()
    if not raw:
        return _CONCURRENCY_DEFAULT
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid %s=%r — using the default cap of %d",
            _CONCURRENCY_ENV_VAR,
            raw,
            _CONCURRENCY_DEFAULT,
        )
        return _CONCURRENCY_DEFAULT


def _enrichment_semaphore() -> asyncio.Semaphore:
    """Semaphore limiting LLM work, (re)built whenever the cap changes or the
    event loop does — a loop-bound primitive reused across loops (tests, or an
    app restart in-process) raises 'bound to a different event loop'."""
    global _semaphore, _semaphore_cap, _semaphore_loop
    cap = enrichment_concurrency()
    loop = asyncio.get_running_loop()
    if _semaphore is None or cap != _semaphore_cap or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(cap)
        _semaphore_cap = cap
        _semaphore_loop = loop
    return _semaphore


class EnrichmentService:
    """Orchestrates background AI tasks after an entry or note is saved."""

    @staticmethod
    def schedule(entry_id: int, title: str | None, body: str) -> None:
        """Fire-and-forget enrichment. Does not block the save response."""
        task = asyncio.create_task(_run_enrichment(entry_id, title, body))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)

    @staticmethod
    def schedule_note(note_id: int, title: str | None, body: str) -> None:
        """Fire-and-forget *embedding-only* enrichment for a note.

        Notes have no sentiment/summary/reflection pipeline (entries only), so
        the note path is the embedding task alone. Never call this with
        ciphertext — callers must skip encrypted notes, exactly like entries.
        """
        task = asyncio.create_task(_run_note_enrichment(note_id, title, body))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)


async def cancel_pending_tasks() -> None:
    """Cancel all outstanding enrichment tasks (for graceful shutdown)."""
    for task in _pending_tasks:
        task.cancel()
    if _pending_tasks:
        await asyncio.gather(*_pending_tasks, return_exceptions=True)
    _pending_tasks.clear()


async def _run_note_enrichment(note_id: int, title: str | None, body: str) -> None:
    """Run the (embedding-only) AI tasks for a saved note."""
    try:
        async with _enrichment_semaphore():
            ollama = OllamaService()
            status = await ollama.status()
            if not status.ollama_available:
                return

            text = f"{title or ''}\n\n{body}".strip()
            if not text.strip() or not settings.AI_ENABLE_EMBEDDINGS:
                return

            await _generate_note_embedding(note_id, text, ollama)
    except Exception:
        logger.exception("Enrichment failed for note %d", note_id)


async def _run_enrichment(entry_id: int, title: str | None, body: str) -> None:
    """Run all enabled AI enrichment tasks for an entry.

    Bounded by :func:`_enrichment_semaphore` so a bulk import can't open an
    unbounded number of Ollama jobs. Each slot may still run its embedding and
    analysis tasks concurrently (they are awaited together), so the real
    in-flight request count is at most ~2x the cap.
    """
    try:
        async with _enrichment_semaphore():
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
    # Imported lazily so a repointed ``app.core.database.async_session`` (tests,
    # restores) is followed — the module-level binding would be stale.
    from app.core.database import async_session

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


async def _generate_note_embedding(note_id: int, text: str, ollama: OllamaService) -> None:
    """Generate and store the note embedding for semantic search.

    Mirrors :func:`_generate_embedding` but writes ``note_embeddings`` and
    updates the note vector cache. Same embed model ⇒ same vector space as
    entries, so one query embedding serves both kinds.
    """
    # Imported lazily so a repointed ``app.core.database.async_session`` (tests,
    # restores) is followed — the module-level binding would be stale.
    from app.core.database import async_session

    try:
        from app.models.embedding import NoteEmbedding

        embedding_vec = await ollama.embed(text)
        embedding_json = json.dumps(embedding_vec)

        async with async_session() as session:
            # Upsert: delete existing, insert new.
            await session.execute(
                NoteEmbedding.__table__.delete().where(NoteEmbedding.note_id == note_id)  # type: ignore[attr-defined]
            )
            session.add(
                NoteEmbedding(
                    note_id=note_id,
                    embedding=embedding_json,
                    model_name=settings.OLLAMA_EMBED_MODEL,
                )
            )
            await session.commit()
        # Keep the in-memory vector cache in sync (best-effort; the per-search
        # count check reloads on any divergence regardless).
        try:
            from app.services.semantic_cache import get_note_semantic_cache

            get_note_semantic_cache().update_entry(note_id, embedding_vec)
        except Exception:
            logger.warning("Failed to update note cache for note %d", note_id, exc_info=True)
        logger.info("Embedding stored for note %d (%d dims)", note_id, len(embedding_vec))

    except Exception:
        logger.exception("Embedding generation failed for note %d", note_id)


# ── Embedding backfill ─────────────────────────────────────────────────────────
# Entries saved while Ollama was down get no embedding at all: the per-save task
# bails out on an unavailable backend and nothing ever retries, so those entries
# stay invisible to semantic/hybrid search until a manual re-save. The sweep
# below heals that: it finds live plaintext entries missing an embedding for the
# *current* model and backfills a small bounded batch. It is triggered lazily
# from the semantic search path (see ``semantic_cache``) — once per process per
# interval, never on a timer, so a scheduler change isn't needed.

# How many entries one sweep embeds (keeps a cold-start burst cheap on CPU).
_BACKFILL_BATCH = 10
# Seconds between sweeps.
_BACKFILL_INTERVAL_SECONDS = 6 * 3600
# Re-arm quickly right after a partial sweep, so a long backlog drains.
_BACKFILL_RETRY_SECONDS = 300

_backfill_last_sweep = 0.0
_backfill_retry_soon = False
_backfill_task: asyncio.Task[None] | None = None


def maybe_schedule_backfill(min_interval_seconds: int = _BACKFILL_INTERVAL_SECONDS) -> bool:
    """Schedule a backfill sweep if enough time has passed. True if scheduled.

    Cheap, lock-free guard: a monotonic timestamp check on the search path. The
    sweep itself runs detached and swallows its own errors.
    """
    global _backfill_last_sweep, _backfill_task

    if not settings.AI_ENABLE_EMBEDDINGS:
        return False
    if settings.APP_ENV == "test":
        # Tests must not fire network calls or background embedding writes —
        # a reachable Ollama would otherwise make search assertions flaky.
        return False
    now = time.monotonic()
    interval = _BACKFILL_RETRY_SECONDS if _backfill_retry_soon else min_interval_seconds
    if now - _backfill_last_sweep < interval:
        return False
    if _backfill_task is not None and not _backfill_task.done():
        return False
    _backfill_last_sweep = now
    task = asyncio.create_task(_backfill_embeddings())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    _backfill_task = task
    return True


async def backfill_missing_embeddings(limit: int = _BACKFILL_BATCH) -> int:
    """Embed live plaintext entries missing an embedding for the current model.

    Returns the number of entries embedded. Bounded so a big backlog can't
    monopolise a local model: callers re-run the sweep later for more.
    """
    from app.core.database import async_session
    from app.models.embedding import EntryEmbedding
    from app.models.entry import Entry

    ollama = OllamaService()
    status = await ollama.status()
    if not status.ollama_available:
        return 0

    async with async_session() as session:
        rows = (
            await session.execute(
                select(Entry.id, Entry.title, Entry.body)
                .outerjoin(
                    EntryEmbedding,
                    (EntryEmbedding.entry_id == Entry.id)
                    & (EntryEmbedding.model_name == settings.OLLAMA_EMBED_MODEL),
                )
                .where(
                    ~Entry.is_deleted,
                    ~Entry.is_encrypted,  # never embed ciphertext
                    EntryEmbedding.id.is_(None),
                )
                .order_by(Entry.entry_date.desc())
                .limit(limit)
            )
        ).all()

    embedded = 0
    for entry_id, title, body in rows:
        text = f"{title or ''}\n\n{body}".strip()
        if not text:
            continue
        try:
            await _generate_embedding(int(entry_id), text, ollama)
            embedded += 1
        except Exception:
            logger.warning("Backfill embedding failed for entry %s", entry_id, exc_info=True)
    if embedded:
        logger.info("Embedding backfill stored %d/%d missing vectors", embedded, len(rows))
    return embedded


async def _backfill_embeddings() -> None:
    """Detected-failure wrapper around :func:`backfill_missing_embeddings`."""
    global _backfill_retry_soon
    try:
        embedded = await backfill_missing_embeddings()
        # More to do? Re-arm on the short interval so the backlog drains.
        _backfill_retry_soon = embedded >= _BACKFILL_BATCH
    except Exception:
        logger.warning("Embedding backfill sweep failed", exc_info=True)
        _backfill_retry_soon = False


async def _analyze_entry(entry_id: int, text: str, ollama: OllamaService) -> None:
    """Run combined sentiment + summary + prompts analysis."""
    from app.core.database import async_session  # lazy — see _generate_embedding

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
