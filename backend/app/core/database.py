"""SQLAlchemy async engine, session factory, and Base declarative model."""
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session per request."""
    async with async_session() as session:
        yield session


async def reinit_engine() -> None:
    """Dispose current engine and create a fresh one (for backup restore)."""
    global engine, async_session
    await engine.dispose()
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
    )
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables (for dev/bootstrap; use Alembic in production)."""
    # Skip production validation for desktop/Tauri sidecar (local-only access)
    import os
    if not os.environ.get("DATA_DIR"):
        settings.validate_production()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure FTS5 virtual table and sync triggers exist
    await _setup_fts()

    # Seed built-in templates (idempotent)
    await _seed_builtin_templates()


async def _setup_fts() -> None:
    """Create FTS5 virtual table if missing, populate, and install sync triggers."""
    async with engine.begin() as conn:
        # Check if FTS table already exists
        exists = (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
            )
        ).scalar()

        if not exists:
            logger.info("Creating FTS5 index and populating...")
            await conn.execute(text("""
                CREATE VIRTUAL TABLE entries_fts
                USING fts5(title, body, content=entries, content_rowid=id)
            """))
            await conn.execute(text("""
                INSERT INTO entries_fts(rowid, title, body)
                SELECT id, COALESCE(title, ''), body FROM entries WHERE is_deleted = 0
            """))
        else:
            # Verify integrity — try a simple query
            try:
                count = (await conn.execute(text("SELECT COUNT(*) FROM entries_fts"))).scalar()
                entry_count = (
                    await conn.execute(text("SELECT COUNT(*) FROM entries WHERE is_deleted = 0"))
                ).scalar()
                if count < entry_count:
                    logger.info("FTS index stale (%d/%d rows), rebuilding...", count, entry_count)
                    await conn.execute(text("DELETE FROM entries_fts"))
                    await conn.execute(text("""
                        INSERT INTO entries_fts(rowid, title, body)
                        SELECT id, COALESCE(title, ''), body FROM entries WHERE is_deleted = 0
                    """))
            except Exception:
                logger.warning("FTS index corrupt, rebuilding...")
                for name in ("fts_entry_ai", "fts_entry_au", "fts_entry_ad", "fts_entry_soft_del"):
                    await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                await conn.execute(text("DROP TABLE IF EXISTS entries_fts"))
                await conn.execute(text("""
                    CREATE VIRTUAL TABLE entries_fts
                    USING fts5(title, body, content=entries, content_rowid=id)
                """))
                await conn.execute(text("""
                    INSERT INTO entries_fts(rowid, title, body)
                    SELECT id, COALESCE(title, ''), body FROM entries WHERE is_deleted = 0
                """))

        # Ensure triggers exist (DROP + CREATE for idempotency)
        for name in ("fts_entry_ai", "fts_entry_au", "fts_entry_ad", "fts_entry_soft_del"):
            await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))

        await conn.execute(text("""
            CREATE TRIGGER fts_entry_ai AFTER INSERT ON entries
            BEGIN
                INSERT INTO entries_fts(rowid, title, body)
                VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER fts_entry_au AFTER UPDATE ON entries
            BEGIN
                UPDATE entries_fts SET title = COALESCE(NEW.title, ''), body = NEW.body
                WHERE rowid = NEW.id;
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER fts_entry_ad AFTER DELETE ON entries
            BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, body)
                VALUES ('delete', OLD.id, COALESCE(OLD.title, ''), OLD.body);
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER fts_entry_soft_del AFTER UPDATE ON entries
            WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
            BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, body)
                VALUES ('delete', NEW.id, COALESCE(NEW.title, ''), NEW.body);
            END
        """))


async def _seed_builtin_templates() -> None:
    from sqlalchemy import select

    from app.models.template import Template

    async with async_session() as session:
        result = await session.execute(select(Template).where(Template.is_builtin.is_(True)).limit(1))
        if result.scalar():
            return  # already seeded

        logger.info("Seeding built-in templates...")
        builtins = [
            Template(
                name="Daily Reflection",
                body="## How I'm feeling\n\n\n## What I did today\n\n\n## Grateful for\n\n",
                is_builtin=True,
            ),
            Template(
                name="Gratitude Journal",
                body="## Three things I'm grateful for\n\n1. \n2. \n3. \n\n## Why\n\n",
                is_builtin=True,
            ),
            Template(
                name="Travel Log",
                body="## Location\n\n\n## Highlights\n\n\n## Photos & Memories\n\n",
                is_builtin=True,
            ),
            Template(
                name="Weekly Review",
                body="## Wins this week\n\n\n## Challenges\n\n\n## Goals for next week\n\n",
                is_builtin=True,
            ),
        ]
        session.add_all(builtins)
        await session.commit()
