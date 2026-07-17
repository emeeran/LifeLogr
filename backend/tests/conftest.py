"""Shared fixtures for integration tests — real async SQLite + FastAPI test client."""

import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
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
async def db_session(db_engine, monkeypatch) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for test assertions.

    Also repoints the app's background ``async_session`` factory
    (``app.core.database.async_session``) at this test engine. Code that runs
    outside FastAPI DI — e.g. the scheduler helpers in ``scheduler_service`` —
    imports ``async_session`` lazily and would otherwise hit the production DB,
    breaking FK integrity against test-seeded rows and hiding background writes
    from assertions.
    """
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    import app.core.database as dbmod

    monkeypatch.setattr(dbmod, "async_session", session_factory)
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


@pytest.fixture(autouse=True)
def _reset_semantic_cache():
    """Isolate the process-wide embedding cache between tests.

    Without this, two tests whose DBs hold the same number of embeddings would
    reuse each other's vectors (the cache's count check only reloads on a count
    mismatch), silently corrupting semantic-search assertions.
    """
    from app.services.semantic_cache import get_semantic_cache

    get_semantic_cache().reset()
    yield
    get_semantic_cache().reset()


@pytest.fixture(autouse=True)
def _isolate_scheduler_singleton():
    """Stop the APScheduler singleton leaking across tests.

    ``AsyncIOScheduler`` binds to the current event loop; with
    ``asyncio_mode = "auto"`` the loop closes at the end of each test. If a
    prior test (e.g. an integration test driving the app via the ``client``
    fixture) left ``scheduler_service._scheduler`` running on that now-closed
    loop, the next test that touches it raises ``RuntimeError: Event loop is
    closed`` — which cascades through every later test in the module. Reset
    (best-effort shutdown, always clear the reference) before and after each
    test so every test starts on a fresh scheduler.
    """
    import app.services.scheduler_service as mod

    def _reset() -> None:
        try:
            sched = getattr(mod, "_scheduler", None)
            if sched is not None and getattr(sched, "running", False):
                sched.shutdown(wait=False)
        except Exception:
            pass
        mod._scheduler = None

    _reset()
    yield
    _reset()

