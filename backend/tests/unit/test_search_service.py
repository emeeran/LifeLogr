"""Integration tests for search — uses LIKE-based search via entries API and direct SearchService filtering."""

import json
from datetime import date
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_service import SearchService
from app.models.entry import Entry
from app.models.embedding import EntryEmbedding


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
