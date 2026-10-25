"""Progress reporting for imports (DM4).

Pins the polled-job contract for data imports:
  * the shared entry-import loop reports dedup → insert → enrich with
    monotonic per-row done/total and actually writes the rows;
  * ``/entries/import/file?as_job=true`` runs the insert as a job that ends
    ``done`` with a human detail (background tasks execute before the ASGI
    transport returns, so the final state is directly assertable);
  * a runner failure lands on the job, not the 202 response.
"""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import jobs
from app.models.entry import Entry
from app.routers.entries import _run_entry_import

from tests.helpers.diarium_diary import build_diary


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


def _collector():
    events: list[tuple[str, int, int | None]] = []

    def report(phase: str, done: int = 0, total: int | None = None, detail=None) -> None:
        events.append((phase, done, total))

    return events, report


def _assert_monotonic(events: list[tuple[str, int, int | None]]) -> None:
    last_done: dict[str, int] = {}
    for phase, done, total in events:
        assert done >= last_done.get(phase, 0)
        last_done[phase] = done
        if total is not None:
            assert done <= total


ENTRIES = [
    {"entry_date": "2026-01-01", "title": "A", "body": "first"},
    {"entry_date": "2026-01-02", "title": "B", "body": "second"},
    {"entry_date": "2026-01-03", "title": "C", "body": "third"},
]


class TestEntryImportProgress:
    async def test_phases_and_rows(self, db_session: AsyncSession) -> None:
        events, report = _collector()
        result = await _run_entry_import(db_session, ENTRIES, skip_duplicates=False, report=report)

        assert result["imported"] == 3
        assert result["skipped"] == 0
        _assert_monotonic(events)
        phases = [p for p, _, _ in events]
        for expected in ("dedup", "insert", "enrich"):
            assert expected in phases
        # Per-row progress covered every record.
        assert events[-2][:2] == ("insert", 3)  # last insert tick, before enrich
        rows = (await db_session.execute(select(Entry))).scalars().all()
        assert len(rows) == 3


class TestImportFileJob:
    async def test_as_job_runs_to_done(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        diary = build_diary(
            [
                {"date": "2026-02-01", "heading": "Day one", "text": "<p>hello</p>"},
                {"date": "2026-02-02", "heading": "Day two", "text": "<p>again</p>"},
            ]
        )
        resp = await client.post(
            "/api/v1/entries/import/file?as_job=true&skip_duplicates=false",
            files={"file": ("backup.diary", diary, "application/octet-stream")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"job_id", "kind"}
        assert body["kind"] == "import-entries"

        job = jobs.get(body["job_id"])
        assert job is not None
        assert job.status == "done"
        assert "Imported" in (job.detail or "")

        rows = (await db_session.execute(select(Entry))).scalars().all()
        assert len(rows) == 2

    async def test_job_failure_lands_on_the_job(self) -> None:
        # Drive the shared 202 wrapper directly: a raising runner must fail
        # the job while the response body is already on the wire.
        from app.core.jobs import start_data_job

        async def runner(report) -> str:
            raise RuntimeError("boom mid-import")

        tasks = BackgroundTasks()
        body = start_data_job(tasks, "import-entries", runner)
        await tasks()

        job = jobs.get(body["job_id"])
        assert job is not None
        assert job.status == "failed"
        assert job.error == "boom mid-import"
