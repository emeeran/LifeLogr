"""Shared fixtures for integration tests — real async SQLite + FastAPI test client."""

import os
import tempfile
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["APP_ENV"] = "test"

from app.core.database import Base, get_db
from app.main import app

_FTS_DDL = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(title, body)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body)",
]


@pytest_asyncio.fixture
async def db_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    url = f"sqlite+aiosqlite:///{tmp.name}"
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in _FTS_DDL:
            await conn.execute(text(ddl))
    yield engine
    await engine.dispose()
    os.unlink(tmp.name)


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for test assertions."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client sharing the same session as db_session to avoid concurrent write corruption."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
