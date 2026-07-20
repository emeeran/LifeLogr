"""Integration tests for search — uses LIKE-based search via entries API and direct SearchService filtering."""

import json
from datetime import date, time
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_service import SearchService
from app.models.entry import Entry
from app.models.embedding import EntryEmbedding
from app.models.reminder import Reminder


class TestSearch:
    async def test_search_returns_results(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "Python programming"}
        )
        # Use the entries search endpoint (which uses ilike fallback when FTS isn't populated)
        r = await client.get("/api/v1/entries/search", params={"q": "Python"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    async def test_search_empty_results(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-05-02", "body": "Hello world"}
        )
        r = await client.get("/api/v1/entries/search", params={"q": "xyznonexistent"})
        assert r.status_code == 200
        assert r.json()["total"] == 0

    @patch("app.services.ollama_service.OllamaService.embed", new_callable=AsyncMock)
    async def test_semantic_search_applies_filters(self, mock_embed, db_session: AsyncSession):
        # Setup mock embedding
        mock_embed.return_value = [0.1, 0.2, 0.3]

        # Create entries with different moods, utilizing real Python date objects
        e1 = Entry(
            entry_date=date(2026, 5, 3), title="Python matching", body="Python body", mood="excited"
        )
        e2 = Entry(
            entry_date=date(2026, 5, 4), title="Python matching", body="Python body", mood="calm"
        )
        db_session.add_all([e1, e2])
        await db_session.flush()

        # Create embeddings corresponding to the entries
        emb1 = EntryEmbedding(entry_id=e1.id, embedding=json.dumps([0.1, 0.2, 0.3]))
        emb2 = EntryEmbedding(entry_id=e2.id, embedding=json.dumps([0.1, 0.2, 0.3]))
        db_session.add_all([emb1, emb2])
        await db_session.commit()

        svc = SearchService(db_session)

        # Search with mood filter "excited" -> should only return e1
        results, total = await svc.search(query="Python", mood="excited", mode="semantic")
        assert total == 1
        assert results[0].id == e1.id

        # Search with mood filter "calm" -> should only return e2
        results, total = await svc.search(query="Python", mood="calm", mode="semantic")
        assert total == 1
        assert results[0].id == e2.id

    async def test_reminder_search(self, db_session: AsyncSession):
        """Reminders (the 'schedule') are included in global search results."""
        r1 = Reminder(
            title="Standup meeting", message="Daily sync notes", reminder_time=time(9, 0)
        )
        r2 = Reminder(title="Gym session", message="Workout", reminder_time=time(18, 0))
        db_session.add_all([r1, r2])
        await db_session.commit()

        svc = SearchService(db_session)
        results, total = await svc.search(query="standup", mode="keyword")
        assert total >= 1
        assert any(item.type == "reminder" and item.id == r1.id for item in results)
        # The non-matching reminder must not appear.
        assert not any(item.id == r2.id for item in results)
