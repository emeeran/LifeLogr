"""Bulk import batching.

``/entries/import`` and ``/entries/import/file`` used to call
``EntryService.create()`` per row, which paid a full ``COMMIT`` (an fsync on
SQLite) per record and scheduled one fire-and-forget enrichment job per row.
They now write a whole chunk in one transaction and queue enrichment only for
committed rows.

The tests below assert on observable behaviour: one commit per chunk, results
identical to the per-row version (including per-row skip accounting), and no
enrichment job for a row that is not yet committed.
"""

from __future__ import annotations

import json
from datetime import date

from httpx import AsyncClient
from sqlalchemy import event, select

from app.models.entry import Entry
from app.services.enrichment_service import EnrichmentService


class _CommitCounter:
    """Count commits on the engine behind the shared test session.

    Listened at the SQLAlchemy Connection layer rather than
    ``after_cursor_execute``: on aiosqlite a COMMIT is issued by the DBAPI's
    ``commit()``, not as a cursor statement, so the cursor event never sees it.
    """

    def __init__(self, db_session) -> None:
        self.count = 0
        # AsyncSession.get_bind() already returns the sync Engine mirror.
        self._engine = db_session.get_bind()
        event.listen(self._engine, "commit", self._on_commit)

    def _on_commit(self, conn) -> None:
        self.count += 1

    def remove(self) -> None:
        event.remove(self._engine, "commit", self._on_commit)


def _rows(n: int, *, prefix: str = "imported body", tag: str | None = None) -> list[dict]:
    rows = [
        {
            "entry_date": f"2026-09-{(i % 28) + 1:02d}",
            "title": f"row {i}",
            "body": f"{prefix} {i} #imported",
        }
        for i in range(n)
    ]
    if tag:
        for r in rows:
            r["tags"] = [tag]
    return rows


class TestBatchedCommit:
    """Commit-count tests must stub enrichment: the real workers open their own
    session on the same engine and commit results, polluting the count (and
    non-deterministically, whenever a live Ollama answers fast enough)."""

    @staticmethod
    def _stub_enrichment(monkeypatch) -> None:
        monkeypatch.setattr(
            EnrichmentService, "schedule", staticmethod(lambda eid, title, body: None)
        )

    async def test_small_import_commits_once(
        self, client: AsyncClient, db_session, monkeypatch
    ):
        self._stub_enrichment(monkeypatch)
        counter = _CommitCounter(db_session)
        try:
            r = await client.post("/api/v1/entries/import", json=_rows(5))
        finally:
            counter.remove()
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 5
        assert counter.count == 1, "5 rows must not mean 5 commits"

    async def test_large_import_commits_in_chunks(
        self, client: AsyncClient, db_session, monkeypatch
    ):
        self._stub_enrichment(monkeypatch)
        from app.routers.entries import _IMPORT_COMMIT_CHUNK

        n = _IMPORT_COMMIT_CHUNK * 2 + 7
        counter = _CommitCounter(db_session)
        try:
            r = await client.post("/api/v1/entries/import", json=_rows(n))
        finally:
            counter.remove()
        assert r.json()["imported"] == n
        assert counter.count == 3, f"expected ceil({n}/{_IMPORT_COMMIT_CHUNK}) commits"

    async def test_all_rows_are_persisted_and_tagged(self, client: AsyncClient, db_session):
        from app.models.tag import Tag

        r = await client.post("/api/v1/entries/import", json=_rows(3, tag="batched"))
        assert r.json()["imported"] == 3

        tag = (await db_session.execute(select(Tag).where(Tag.name == "batched"))).scalar_one()
        assert tag.id is not None

    async def test_import_file_path_is_batched_too(
        self, client: AsyncClient, db_session, monkeypatch
    ):
        self._stub_enrichment(monkeypatch)
        counter = _CommitCounter(db_session)
        try:
            r = await client.post(
                "/api/v1/entries/import/file",
                files={
                    "file": (
                        "exp.json",
                        json.dumps({"entries": _rows(4)}).encode(),
                        "application/json",
                    )
                },
            )
        finally:
            counter.remove()
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 4
        assert counter.count == 1


class TestPartialImportSemantics:
    async def test_one_bad_row_does_not_lose_the_rest_of_its_chunk(
        self, client: AsyncClient, db_session
    ):
        rows: list[dict] = []
        for i in range(4):
            rows.append({"entry_date": f"2026-10-{i + 1:02d}", "body": f"good row {i}"})
        # A row the schema rejects (latitude out of range) lands mid-chunk.
        rows.insert(2, {"entry_date": "2026-10-20", "body": "bad", "latitude": 999.0})
        # And one with neither date nor body is skipped up front.
        rows.insert(4, {"title": "no date, no body"})

        r = await client.post("/api/v1/entries/import", json=rows)
        assert r.status_code == 200
        body = r.json()
        assert body["imported"] == 4
        assert body["skipped"] == 2
        reasons = {x["index"]: x["reason"] for x in body["skip_reasons"]}
        assert "latitude" in reasons[2]
        assert reasons[4] == "missing entry_date or body"

        stored = (
            await db_session.execute(
                select(Entry).where(Entry.entry_date >= date(2026, 10, 1))
            )
        ).scalars().all()
        assert {e.body for e in stored} == {"good row 0", "good row 1", "good row 2", "good row 3"}

    async def test_the_failing_row_itself_is_not_persisted(self, client: AsyncClient, db_session):
        r = await client.post(
            "/api/v1/entries/import",
            json=[{"entry_date": "2026-10-21", "body": "x" * 2_000_000}],
        )
        assert r.status_code == 200
        assert r.json()["skipped"] == 1
        count = (
            await db_session.execute(select(Entry).where(Entry.entry_date == date(2026, 10, 21)))
        ).scalar_one_or_none()
        assert count is None


class TestEnrichmentDeferred:
    async def test_enrichment_runs_once_per_imported_row_after_commit(
        self, client: AsyncClient, monkeypatch
    ):
        calls: list[int] = []
        monkeypatch.setattr(
            EnrichmentService, "schedule", staticmethod(lambda eid, title, body: calls.append(eid))
        )
        r = await client.post("/api/v1/entries/import", json=_rows(3))
        assert r.json()["imported"] == 3
        assert len(calls) == 3
        assert len(set(calls)) == 3

    async def test_no_enrichment_job_for_a_skipped_row(self, client: AsyncClient, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(
            EnrichmentService, "schedule", staticmethod(lambda eid, title, body: calls.append(eid))
        )
        r = await client.post(
            "/api/v1/entries/import",
            json=[
                {"entry_date": "2026-10-22", "body": "kept"},
                {"title": "dropped"},
            ],
        )
        body = r.json()
        assert body["imported"] == 1 and body["skipped"] == 1
        assert len(calls) == 1
