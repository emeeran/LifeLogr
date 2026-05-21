"""Integration tests for revisions — snapshot, list, diff, restore."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.services.revision_service import RevisionService


async def _entry_with_revisions(client: AsyncClient, db_session: AsyncSession, n=3):
    """Create entry via API + n revisions via direct service call."""
    r = await client.post("/api/v1/entries", json={"entry_date": "2026-05-01", "body": "v0"})
    entry_id = r.json()["id"]
    entry = await db_session.get(Entry, entry_id)
    svc = RevisionService(db_session)
    for i in range(1, n + 1):
        entry.body = f"v{i}"
        await db_session.commit()
        await db_session.refresh(entry)
        await svc.create_snapshot(entry)
    return entry_id


class TestRevisions:
    async def test_list_revisions_empty(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-06-01", "body": "v1"})
        e = r.json()
        r = await client.get(f"/api/v1/entries/{e['id']}/revisions")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    async def test_list_revisions(self, client: AsyncClient, db_session: AsyncSession):
        eid = await _entry_with_revisions(client, db_session, 3)
        r = await client.get(f"/api/v1/entries/{eid}/revisions")
        assert r.json()["total"] == 3

    async def test_get_specific_revision(self, client: AsyncClient, db_session: AsyncSession):
        eid = await _entry_with_revisions(client, db_session, 2)
        r = await client.get(f"/api/v1/entries/{eid}/revisions/1")
        assert r.status_code == 200

    async def test_get_missing_revision_404(self, client: AsyncClient):
        r = await client.post("/api/v1/entries", json={"entry_date": "2026-06-02", "body": "x"})
        e = r.json()
        r = await client.get(f"/api/v1/entries/{e['id']}/revisions/99")
        assert r.status_code == 404

    async def test_diff_revisions(self, client: AsyncClient, db_session: AsyncSession):
        eid = await _entry_with_revisions(client, db_session, 2)
        r = await client.get(f"/api/v1/entries/{eid}/revisions/1/diff/2")
        assert r.status_code == 200

    async def test_restore_revision(self, client: AsyncClient, db_session: AsyncSession):
        eid = await _entry_with_revisions(client, db_session, 2)
        r = await client.post(f"/api/v1/entries/{eid}/revisions/1/restore")
        assert r.status_code == 200
