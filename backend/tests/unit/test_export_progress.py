"""Progress reporting for exports (DM5).

Pins:
  * build_archive reports per-media-file progress then finalize;
  * start_export_job produces a downloadable result served once by
    GET /jobs/{id}/result (second download → 410, file deleted);
  * a failed export build lands on the job, not the 202 response.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient

from app.core.config import settings
from app.core.jobs import jobs, start_export_job


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


def _fake_entry(tmp_path, media_count: int) -> SimpleNamespace:
    media = []
    for i in range(media_count):
        p = tmp_path / f"m{i}.jpg"
        p.write_bytes(b"jpeg")
        media.append(
            SimpleNamespace(
                id=100 + i,
                storage_path=p.name,
                filename=f"m{i}.jpg",
                media_type="image",
                caption=None,
                is_inline=True,
            )
        )
    return SimpleNamespace(
        entry_date="2026-01-01",
        title="T",
        body="b",
        mood=None,
        latitude=None,
        longitude=None,
        tag_associations=[],
        media=media,
    )


def _collector():
    events: list[tuple[str, int, int | None]] = []

    def report(phase: str, done: int = 0, total: int | None = None) -> None:
        events.append((phase, done, total))

    return events, report


class TestArchiveExportProgress:
    def test_media_then_finalize(self, tmp_path, monkeypatch) -> None:
        from app.services.export_service import build_archive

        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        events, report = _collector()
        data = build_archive([_fake_entry(tmp_path, 2)], report=report)

        assert data.read_bytes()[:2] == b"PK"  # a real zip
        data.unlink(missing_ok=True)
        phases = [p for p, _, _ in events]
        assert phases[0] == "media"
        assert phases[-1] == "finalize"
        assert events[-2] == ("media", 2, 2)  # both files reported
        for _, done, total in events[:-1]:
            assert done <= total


    def test_zero_media_no_nan(self, tmp_path, monkeypatch) -> None:
        from app.services.export_service import build_archive

        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        events, report = _collector()
        data = build_archive([_fake_entry(tmp_path, 0)], report=report)

        assert data.read_bytes()[:2] == b"PK"
        data.unlink(missing_ok=True)
        assert ("media", 0, 0) in events
        assert events[-1] == ("finalize", 1, 1)
        # total=0 → the registry reports percent=None (indeterminate), never 0/0.
        job = jobs.create("export-archive")
        jobs.update(job.id, "media", 0, 0)
        assert jobs.get(job.id).percent is None


class TestExportJob:
    async def test_result_roundtrip(self, client: AsyncClient, tmp_path) -> None:
        async def builder(report, session):
            report("render", 1, 1)
            return b"export-bytes"

        tasks = BackgroundTasks()
        body = start_export_job(
            tasks, "export-archive", "out.zip", builder, session_factory=None
        )
        await tasks()

        job = jobs.get(body["job_id"])
        assert job is not None
        assert job.status == "done"
        assert job.result_name == "out.zip"

        resp = await client.get(f"/api/v1/jobs/{body['job_id']}/result")
        assert resp.status_code == 200
        assert resp.content == b"export-bytes"
        assert "attachment" in resp.headers.get("content-disposition", "")
        # Served once — the temp file is deleted behind the response.
        resp2 = await client.get(f"/api/v1/jobs/{body['job_id']}/result")
        assert resp2.status_code == 410

    async def test_builder_failure_marks_job_failed(self) -> None:
        async def builder(report, session):
            raise RuntimeError("disk blew up")

        tasks = BackgroundTasks()
        body = start_export_job(tasks, "export-archive", "out.zip", builder)
        await tasks()

        job = jobs.get(body["job_id"])
        assert job is not None
        assert job.status == "failed"
        assert "disk blew up" in (job.error or "")
        assert jobs.take_result(body["job_id"]) is None
