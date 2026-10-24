"""Integration tests for the destructive database-reset endpoint."""

from datetime import date

from sqlalchemy import text

from app.models.entry import Entry


class TestResetEndpoint:
    async def _seed_entry(self, db_session):
        db_session.add(Entry(entry_date=date(2026, 1, 1), title="t", body="b"))
        await db_session.commit()

    async def test_reset_without_confirm_rejected(self, client, db_session):
        await self._seed_entry(db_session)
        resp = await client.post("/api/v1/entries/reset")
        assert resp.status_code == 422  # missing body

    async def test_reset_wrong_confirm_rejected(self, client, db_session):
        await self._seed_entry(db_session)
        for bad in ("reset", "DELETE ALL", "yes", ""):
            resp = await client.post("/api/v1/entries/reset", json={"confirm": bad})
            assert resp.status_code == 400, bad
        remaining = (await db_session.execute(text("SELECT COUNT(*) FROM entries"))).scalar()
        assert remaining == 1  # nothing was wiped by rejected attempts

    async def test_reset_with_confirm_wipes(self, client, db_session):
        await self._seed_entry(db_session)
        resp = await client.post("/api/v1/entries/reset", json={"confirm": "RESET"})
        assert resp.status_code == 200
        await db_session.commit()
        remaining = (await db_session.execute(text("SELECT COUNT(*) FROM entries"))).scalar()
        assert remaining == 0
