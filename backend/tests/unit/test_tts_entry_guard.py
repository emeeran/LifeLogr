"""TTS entry endpoint guard — deleted and encrypted entries are never spoken."""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entry import Entry
from app.routers.tts import _get_speakable_entry


async def _entry(db_session: AsyncSession, **kwargs) -> Entry:
    fields = {"entry_date": date(2026, 1, 1), "title": "t", "body": "read me"}
    fields.update(kwargs)
    entry = Entry(**fields)
    db_session.add(entry)
    await db_session.commit()
    return entry


class TestSpeakableEntryGuard:
    async def test_live_entry_returns(self, db_session: AsyncSession):
        entry = await _entry(db_session)
        assert (await _get_speakable_entry(db_session, entry.id)).id == entry.id

    async def test_missing_entry_is_404(self, db_session: AsyncSession):
        with pytest.raises(NotFoundError):
            await _get_speakable_entry(db_session, 99999)

    async def test_soft_deleted_entry_is_404(self, db_session: AsyncSession):
        entry = await _entry(db_session, is_deleted=True, deleted_at=None)
        with pytest.raises(NotFoundError):
            await _get_speakable_entry(db_session, entry.id)

    async def test_encrypted_entry_is_409(self, db_session: AsyncSession):
        """Encrypted bodies hold base64 ciphertext — reading them aloud is a bug."""
        entry = await _entry(db_session, is_encrypted=True, body="Y2lwaGVydGV4dA==")
        with pytest.raises(ConflictError):
            await _get_speakable_entry(db_session, entry.id)

    async def test_deleted_wins_over_encrypted(self, db_session: AsyncSession):
        entry = await _entry(db_session, is_deleted=True, is_encrypted=True)
        with pytest.raises(NotFoundError):
            await _get_speakable_entry(db_session, entry.id)


class TestSynthLockBounds:
    """The per-key lock map must stay bounded (it grew forever before)."""

    async def test_lock_map_is_capped(self, monkeypatch):
        from app.routers import tts

        monkeypatch.setattr(tts, "_MAX_SYNTH_LOCKS", 8)
        monkeypatch.setattr(tts, "_locks", tts.OrderedDict())
        try:
            for i in range(50):
                await tts._get_lock(f"key-{i}")
            assert len(tts._locks) <= 8
        finally:
            tts._locks.clear()

    async def test_locked_entries_are_not_evicted(self, monkeypatch):
        from app.routers import tts

        monkeypatch.setattr(tts, "_MAX_SYNTH_LOCKS", 2)
        monkeypatch.setattr(tts, "_locks", tts.OrderedDict())
        try:
            held = await tts._get_lock("held")
            await held.acquire()  # locked → must survive the sweep
            for i in range(20):
                await tts._get_lock(f"key-{i}")
            assert "held" in tts._locks
        finally:
            tts._locks.clear()
