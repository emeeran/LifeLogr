"""Hybrid search totals + mode semantics.

``_hybrid_search`` used to report ``total = len(merged)`` — capped at the two
100-item sub-search pages — and its keyword/semantic-only fallbacks returned the
*page* length as the total, so pagination under-reported on any query matching
more than a page.
"""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.services.search_service import SearchService


async def _entries(
    db_session: AsyncSession, count: int, body: str = "alpha beta gamma"
) -> list[Entry]:
    entries = [
        Entry(entry_date=date(2026, 5, day), title=f"t{i}", body=body)
        for i, day in enumerate(range(1, count + 1), start=1)
    ]
    db_session.add_all(entries)
    await db_session.commit()
    return entries


class TestHybridTotals:
    async def test_keyword_fallback_reports_real_total(self, db_session: AsyncSession):
        """Semantic failing must not shrink the reported total to the page size."""
        await _entries(db_session, 3)
        svc = SearchService(db_session)
        with patch(
            "app.services.ollama_service.OllamaService.embed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ollama down"),
        ):
            items, total = await svc.search("alpha", mode="hybrid", offset=0, limit=2)
        assert len(items) == 2  # the page
        assert total == 3  # the real match count, not len(items)

    async def test_semantic_fallback_reports_real_total(self, db_session: AsyncSession):
        await _entries(db_session, 3)
        svc = SearchService(db_session)
        # No embeddings at all → semantic side is empty, keyword side drives.
        items, total = await svc.search("beta", mode="hybrid", offset=0, limit=2)
        assert len(items) == 2
        assert total == 3

    async def test_union_total_from_sub_totals(self, db_session: AsyncSession):
        """Both sides matching the same rows: union = kw + sem − overlap."""
        entries = await _entries(db_session, 3)
        db_session.add_all(
            [
                EntryEmbedding(entry_id=e.id, embedding=json.dumps([1.0, 0.0, 0.0]))
                for e in entries
            ]
        )
        await db_session.commit()
        svc = SearchService(db_session)
        with patch(
            "app.services.ollama_service.OllamaService.embed",
            new_callable=AsyncMock,
            return_value=[1.0, 0.0, 0.0],
        ):
            items, total = await svc.search("alpha", mode="hybrid", offset=0, limit=2)
        assert len(items) == 2
        assert total == 3  # 3 keyword + 3 semantic − 3 overlapping


class TestModeSemantics:
    async def test_semantic_mode_skips_notes_and_reminders(self, db_session: AsyncSession):
        """Notes/reminders have no embeddings — semantic mode is entries-only."""
        from datetime import time

        from app.models.note import Note
        from app.models.reminder import Reminder

        entry = (await _entries(db_session, 1, body="uniquekeyword entry body"))[0]
        db_session.add(EntryEmbedding(entry_id=entry.id, embedding=json.dumps([1.0, 0.0])))
        db_session.add(Note(title="n", body="uniquekeyword note body"))
        db_session.add(Reminder(title="uniquekeyword reminder", reminder_time=time(9, 0)))
        await db_session.commit()

        svc = SearchService(db_session)
        with patch(
            "app.services.ollama_service.OllamaService.embed",
            new_callable=AsyncMock,
            return_value=[1.0, 0.0],
        ):
            items, total = await svc.search("uniquekeyword", mode="semantic")
        assert {i.type for i in items} == {"entry"}
        assert total == 1

    async def test_keyword_mode_still_includes_notes_and_reminders(
        self, db_session: AsyncSession
    ):
        from datetime import time

        from app.models.note import Note
        from app.models.reminder import Reminder

        db_session.add(Note(title="standup note", body="keywordmode"))
        db_session.add(Reminder(title="keywordmode standup", reminder_time=time(9, 0)))
        await db_session.commit()

        svc = SearchService(db_session)
        items, _total = await svc.search("keywordmode", mode="keyword")
        assert {i.type for i in items} == {"note", "reminder"}


class TestSearchEndpointIntegration:
    async def test_global_search_hybrid_total_via_api(self, client: AsyncClient):
        for i in range(3):
            await client.post(
                "/api/v1/entries",
                json={"entry_date": f"2026-06-0{i + 1}", "body": "paginated token here"},
            )
        r = await client.get(
            "/api/v1/search", params={"q": "paginated", "mode": "hybrid", "limit": 2}
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] >= 3
