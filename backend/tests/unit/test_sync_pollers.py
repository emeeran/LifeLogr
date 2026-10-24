"""Offline sync queue — the replacement for the removed background sync pollers.

The tests that once lived here (``test_pause_then_resume_background_syncs`` and
``test_absent_jobs_report_absent``) covered a background poller that drained the
sync queue on a timer. That poller no longer exists: cloud sync is now explicit
(``/api/v1/sync/cloud/push`` / ``pull``) plus the backup scheduler, and the
local queue is drained only when the client asks ``/api/v1/sync/flush``. The two
names are kept against the *current* behaviour, which is what replaced them:

- work enqueued while the app is offline ("paused") accumulates untouched and is
  drained ("resumed") by an explicit flush, which stamps ``synced_at`` and
  leaves the provider idle;
- a provider with no queued work reports itself idle with a zero backlog —
  status is created on demand rather than erroring.
"""

from __future__ import annotations

from datetime import date

from httpx import AsyncClient
from sqlalchemy import select

from app.models.sync import SyncQueue, SyncStatus


async def _enqueue(client: AsyncClient, operation: str, entity_id: int) -> None:
    r = await client.post(
        "/api/v1/sync/enqueue",
        json={
            "operation": operation,
            "entity_type": "entry",
            "entity_id": entity_id,
            "payload": {"id": entity_id},
        },
    )
    assert r.status_code == 201, r.text


class TestPauseThenResumeBackgroundSyncs:
    async def test_ops_queue_while_offline_and_flush_drains_them(
        self, client: AsyncClient, db_session
    ):
        # ── "paused": nothing syncs on its own, work just accumulates ──
        for i, op in enumerate(("create", "update", "delete"), start=1):
            await _enqueue(client, op, entity_id=i)

        pending = (await client.get("/api/v1/sync/pending")).json()
        assert [item["operation"] for item in pending] == ["create", "update", "delete"]
        assert all(not item["is_synced"] for item in pending)
        assert all(item["synced_at"] is None for item in pending)

        status = (await client.get("/api/v1/sync/status")).json()
        assert status["pending_count"] == 3
        assert status["status"] == "idle"
        assert status["last_sync_at"] is None

        # Rows are still queued in the DB, not merely filtered in the response.
        queued = (
            (await db_session.execute(select(SyncQueue).order_by(SyncQueue.id)))
            .scalars()
            .all()
        )
        assert len(queued) == 3

        # ── "resumed": an explicit flush drains the backlog ──
        flushed = await client.post("/api/v1/sync/flush")
        assert flushed.status_code == 200
        assert flushed.json() == {"synced": 3, "provider": "local"}

        assert (await client.get("/api/v1/sync/pending")).json() == []
        status = (await client.get("/api/v1/sync/status")).json()
        assert status["pending_count"] == 0
        assert status["status"] == "idle"
        assert status["last_sync_at"] is not None

        rows = (
            (await db_session.execute(select(SyncQueue).order_by(SyncQueue.id)))
            .scalars()
            .all()
        )
        assert [r.is_synced for r in rows] == [True, True, True]
        assert all(r.synced_at is not None for r in rows)

    async def test_queue_rearms_after_a_flush(self, client: AsyncClient):
        """Draining the backlog does not retire the queue: new work queues again."""
        await _enqueue(client, "create", entity_id=1)
        assert (await client.post("/api/v1/sync/flush")).json()["synced"] == 1

        await _enqueue(client, "update", entity_id=2)
        status = (await client.get("/api/v1/sync/status")).json()
        assert status["pending_count"] == 1
        assert [i["entity_id"] for i in (await client.get("/api/v1/sync/pending")).json()] == [2]

    async def test_flush_only_touches_the_sync_queue(self, client: AsyncClient, db_session):
        """A flush is bookkeeping: it must not modify the entries it refers to."""
        from app.models.entry import Entry

        db_session.add(Entry(entry_date=date(2026, 10, 1), body="body stays put"))
        await db_session.commit()

        await _enqueue(client, "create", entity_id=1)
        assert (await client.post("/api/v1/sync/flush")).json()["synced"] == 1

        row = (
            await db_session.execute(select(Entry).where(Entry.entry_date == date(2026, 10, 1)))
        ).scalar_one()
        assert row.body == "body stays put"


class TestAbsentJobsReportAbsent:
    async def test_status_for_a_provider_with_no_queue_is_idle_and_empty(
        self, client: AsyncClient, db_session
    ):
        r = await client.get("/api/v1/sync/status", params={"provider": "unused-provider"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "provider": "unused-provider",
            "last_sync_at": None,
            "status": "idle",
            "pending_count": 0,
        }

        # The on-demand status row exists and is idle — not an error state.
        row = (
            await db_session.execute(
                select(SyncStatus).where(SyncStatus.provider == "unused-provider")
            )
        ).scalar_one()
        assert row.status == "idle"
        assert row.error_message is None
        assert row.last_sync_at is None

    async def test_pending_is_empty_when_nothing_was_ever_enqueued(self, client: AsyncClient):
        assert (await client.get("/api/v1/sync/pending")).json() == []

    async def test_flush_with_an_empty_backlog_reports_zero(self, client: AsyncClient):
        r = await client.post("/api/v1/sync/flush", params={"provider": "local"})
        assert r.status_code == 200
        assert r.json() == {"synced": 0, "provider": "local"}

    async def test_absent_entities_are_not_invented_by_the_service_layer(self, db_session):
        """SyncService reports what is there — no phantom rows, no defaults."""
        from app.services.cloud_sync_service import SyncService

        svc = SyncService(db_session)
        assert await svc.get_pending() == []
        assert await svc.get_pending_count() == 0
        assert await svc.flush("local") == {"synced": 0, "provider": "local"}
