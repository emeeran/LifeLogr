"""Embedding backfill sweep — entries that missed enrichment get found again."""

from datetime import date
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.services import enrichment_service as enrich


async def _entry(db_session: AsyncSession, body: str = "", **kwargs) -> Entry:
    fields = {"entry_date": date(2026, 3, 1), "title": "t", "body": body}
    fields.update(kwargs)
    entry = Entry(**fields)
    db_session.add(entry)
    await db_session.commit()
    return entry


async def _models(db_session: AsyncSession) -> set[int]:
    rows = await db_session.execute(select(EntryEmbedding.entry_id))
    return {int(r[0]) for r in rows.fetchall()}


class TestBackfillMissingEmbeddings:
    async def test_backfills_missing_entry(self, db_session: AsyncSession):
        entry = await _entry(db_session, "needs a vector")
        from app.schemas.ai import AIStatusResponse

        with (
            patch.object(
                enrich.OllamaService,
                "status",
                new_callable=AsyncMock,
                return_value=AIStatusResponse(
                    ollama_available=True, model_name="m", model_loaded=True, model_names=["m"]
                ),
            ),
            patch.object(
                enrich.OllamaService, "embed", new_callable=AsyncMock, return_value=[1.0, 0.0]
            ) as embed,
        ):
            embedded = await enrich.backfill_missing_embeddings()

        assert embedded == 1
        embed.assert_awaited_once()
        assert await _models(db_session) == {entry.id}

    async def test_skips_encrypted_and_deleted(self, db_session: AsyncSession):
        await _entry(db_session, "ciphertext", is_encrypted=True)
        await _entry(db_session, "gone", is_deleted=True)
        await _entry(db_session, title="", body="")

        from app.schemas.ai import AIStatusResponse

        with (
            patch.object(
                enrich.OllamaService,
                "status",
                new_callable=AsyncMock,
                return_value=AIStatusResponse(
                    ollama_available=True, model_name="m", model_loaded=True, model_names=["m"]
                ),
            ),
            patch.object(
                enrich.OllamaService, "embed", new_callable=AsyncMock, return_value=[1.0, 0.0]
            ) as embed,
        ):
            embedded = await enrich.backfill_missing_embeddings()

        assert embedded == 0
        embed.assert_not_awaited()
        assert await _models(db_session) == set()

    async def test_existing_current_model_row_not_reembedded(self, db_session: AsyncSession):
        entry = await _entry(db_session, "already done")
        db_session.add(
            EntryEmbedding(
                entry_id=entry.id,
                embedding="[0.1, 0.2]",
                model_name=settings.OLLAMA_EMBED_MODEL,
            )
        )
        await db_session.commit()

        from app.schemas.ai import AIStatusResponse

        with (
            patch.object(
                enrich.OllamaService,
                "status",
                new_callable=AsyncMock,
                return_value=AIStatusResponse(
                    ollama_available=True, model_name="m", model_loaded=True, model_names=["m"]
                ),
            ),
            patch.object(
                enrich.OllamaService, "embed", new_callable=AsyncMock
            ) as embed,
        ):
            embedded = await enrich.backfill_missing_embeddings()

        assert embedded == 0
        embed.assert_not_awaited()

    async def test_unavailable_backend_backfills_nothing(self, db_session: AsyncSession):
        await _entry(db_session, "waiting for ollama")

        from app.schemas.ai import AIStatusResponse

        with patch.object(
            enrich.OllamaService,
            "status",
            new_callable=AsyncMock,
            return_value=AIStatusResponse(
                ollama_available=False, model_name="m", model_loaded=False, model_names=[]
            ),
        ):
            assert await enrich.backfill_missing_embeddings() == 0
        assert await _models(db_session) == set()


class TestScheduleGuard:
    async def test_never_schedules_in_test_env(self):
        """Tests must not fire background network calls / writes."""
        assert enrich.maybe_schedule_backfill() is False

    async def test_stale_model_row_is_reembedded(self, db_session: AsyncSession):
        """A vector from a previous embed model doesn't satisfy the sweep."""
        entry = await _entry(db_session, "stale model")
        db_session.add(
            EntryEmbedding(entry_id=entry.id, embedding="[0.5]", model_name="old-model")
        )
        await db_session.commit()

        from app.schemas.ai import AIStatusResponse

        with (
            patch.object(
                enrich.OllamaService,
                "status",
                new_callable=AsyncMock,
                return_value=AIStatusResponse(
                    ollama_available=True, model_name="m", model_loaded=True, model_names=["m"]
                ),
            ),
            patch.object(
                enrich.OllamaService, "embed", new_callable=AsyncMock, return_value=[1.0, 0.0]
            ),
        ):
            assert await enrich.backfill_missing_embeddings() == 1
