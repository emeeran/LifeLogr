"""Tests for the daily incremental-vacuum maintenance job."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import database as dbmod
from app.core.database import _set_sqlite_pragma
from app.services.scheduler_service import _run_incremental_vacuum


@pytest.mark.asyncio
async def test_vacuum_skips_when_not_incremental(db_session) -> None:
    """On a non-INCREMENTAL DB the job is a safe no-op (the conftest engine has
    no auto_vacuum listener, so the test DB defaults to NONE)."""
    # Must not raise and must not attempt the write pragma.
    await _run_incremental_vacuum()


@pytest.mark.asyncio
async def test_vacuum_runs_on_incremental_db(tmp_path, monkeypatch) -> None:
    """On an auto_vacuum=INCREMENTAL DB the job runs the reclamation pragma."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'vac.db'}")
    event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)  # auto_vacuum=INCREMENTAL
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    # _run_incremental_vacuum imports async_session lazily from app.core.database.
    monkeypatch.setattr(dbmod, "async_session", factory)
    try:
        async with eng.begin() as conn:
            await conn.execute(text("CREATE TABLE t (x INTEGER)"))
            await conn.execute(text("INSERT INTO t VALUES (1), (2), (3)"))

        await _run_incremental_vacuum()  # runs PRAGMA incremental_vacuum(100), no raise

        async with factory() as session:
            assert (await session.execute(text("PRAGMA auto_vacuum"))).scalar() == 2
            assert (await session.execute(text("SELECT COUNT(*) FROM t"))).scalar() == 3
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_vacuum_never_raises_on_error(monkeypatch) -> None:
    """A maintenance job must never wedge the scheduler — failures are swallowed."""

    def boom(*a, **k):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(dbmod, "async_session", boom)
    await _run_incremental_vacuum()  # should log + return, not raise
