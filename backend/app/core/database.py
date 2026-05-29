"""SQLAlchemy async engine, session factory, and Base declarative model."""

import asyncio
import logging
import sys
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event, func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_engine() -> tuple:
    """Create a new async engine and session factory.  Single source of truth for all params."""
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    eng = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=1 if is_sqlite else settings.DB_POOL_SIZE,
        max_overflow=0 if is_sqlite else settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )
    if is_sqlite:
        event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, factory


def _set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
    """Enable WAL mode and foreign key enforcement for SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


_engine_lock = asyncio.Lock()

engine, async_session = _build_engine()


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session per request with automatic rollback on error."""
    async with _engine_lock:
        factory = async_session
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def reinit_engine() -> None:
    """Dispose current engine and create a fresh one (for backup restore).

    Swaps globals *before* disposing the old engine so that in-flight
    requests holding a reference to the old session factory continue to
    work while the old engine is drained.
    """
    global engine, async_session
    async with _engine_lock:
        old = engine
        engine, async_session = _build_engine()
        await old.dispose()


async def validate_db_health() -> None:
    """Pre-flight checks before the app starts serving traffic.

    Verifies DATA_DIR writability, DB file accessibility (when it exists),
    SQLite integrity, and FTS5 availability.
    """
    import os
    import tempfile

    data_dir = settings.DATA_DIR

    # 1. DATA_DIR must be writable
    try:
        with tempfile.TemporaryFile(dir=str(data_dir)):
            pass
    except OSError as exc:
        raise RuntimeError(f"DATA_DIR {data_dir!s} is not writable: {exc}") from exc

    if not settings.DATABASE_URL.startswith("sqlite"):
        return  # further checks are SQLite-specific

    db_path = settings.db_path

    # 2. If DB file exists, verify read/write + integrity
    if db_path.exists():
        if not os.access(str(db_path), os.R_OK | os.W_OK):
            raise RuntimeError(f"Database file {db_path!s} is not readable/writable")

        async with engine.begin() as conn:
            result = await conn.execute(text("PRAGMA integrity_check"))
            row = result.scalar()
            if row != "ok":
                raise RuntimeError(
                    f"SQLite integrity check failed: {row}"
                )

    # 3. Verify FTS5 is available (soft check — warn, don't abort)
    _fts5_available = False
    async with engine.begin() as conn:
        try:
            await conn.execute(
                text("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)")
            )
            await conn.execute(text("DROP TABLE IF EXISTS _fts5_check"))
            _fts5_available = True
        except Exception as exc:
            logger.warning(
                "SQLite FTS5 extension is not available: %s. "
                "Full-text search will not work.",
                exc,
            )

    logger.info("Database health check passed")


async def init_db() -> None:
    """Create all tables (for dev/bootstrap; use Alembic in production)."""
    # Skip production validation for desktop/Tauri sidecar (local-only access)
    import os

    if not os.environ.get("DATA_DIR"):
        settings.validate_production()

    await validate_db_health()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)

    # Ensure FTS5 virtual table and sync triggers exist.
    # Skip in PyInstaller builds — FTS virtual table creation can corrupt
    # the schema cache, breaking all subsequent qualified column queries.
    if not getattr(sys, "frozen", False):
        await _setup_fts()
    else:
        logger.info("FTS setup skipped (frozen build)")

    # Seed built-in templates (idempotent)
    await _seed_builtin_templates()


# Lightweight column migrations for desktop (no Alembic).
# Each entry: (table, column, sql). Safe to run on every startup — skipped if column exists.
_COLUMN_MIGRATIONS = [
    ("entries", "summary", "ALTER TABLE entries ADD COLUMN summary VARCHAR(500)"),
    ("entries", "title", "ALTER TABLE entries ADD COLUMN title VARCHAR(255)"),
    ("entries", "mood", "ALTER TABLE entries ADD COLUMN mood VARCHAR(50)"),
    ("entries", "deleted_at", "ALTER TABLE entries ADD COLUMN deleted_at DATETIME"),
    ("entries", "encrypted_at", "ALTER TABLE entries ADD COLUMN encrypted_at DATETIME"),
    ("entries", "latitude", "ALTER TABLE entries ADD COLUMN latitude FLOAT"),
    ("entries", "longitude", "ALTER TABLE entries ADD COLUMN longitude FLOAT"),
    ("entries", "location_name", "ALTER TABLE entries ADD COLUMN location_name VARCHAR(255)"),
    ("entries", "created_at", "ALTER TABLE entries ADD COLUMN created_at DATETIME DEFAULT '1970-01-01 00:00:00'"),
    ("entries", "updated_at", "ALTER TABLE entries ADD COLUMN updated_at DATETIME DEFAULT '1970-01-01 00:00:00'"),
]

_INDEX_MIGRATIONS = [
    ("ix_entries_deleted_date", "CREATE INDEX IF NOT EXISTS ix_entries_deleted_date ON entries (is_deleted, entry_date)"),
    ("ix_entries_deleted_mood", "CREATE INDEX IF NOT EXISTS ix_entries_deleted_mood ON entries (is_deleted, mood)"),
    ("ix_entry_tags_tag_id", "CREATE INDEX IF NOT EXISTS ix_entry_tags_tag_id ON entry_tags (tag_id)"),
]


async def _migrate_schema(conn: Any) -> None:
    """Add missing columns and indexes to existing tables (idempotent)."""
    for table, column, sql in _COLUMN_MIGRATIONS:
        existing = {
            row[1] for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        }
        if column not in existing:
            logger.info("Adding column %s.%s ...", table, column)
            await conn.execute(text(sql))

    # Ensure performance indexes exist
    existing_indexes = {
        row[1]
        for row in (
            await conn.execute(text("SELECT type, name FROM sqlite_master WHERE type='index'"))
        ).fetchall()
    }
    for idx_name, sql in _INDEX_MIGRATIONS:
        if idx_name not in existing_indexes:
            logger.info("Creating index %s ...", idx_name)
            await conn.execute(text(sql))


async def _setup_fts() -> None:
    """Create FTS5 virtual table if missing, populate, and install sync triggers."""
    try:
        async with engine.begin() as conn:
            # Check if FTS table already exists
            exists = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
                )
            ).scalar()

            if not exists:
                logger.info("Creating FTS5 index and populating...")
                await conn.execute(
                    text("""
                    CREATE VIRTUAL TABLE entries_fts
                    USING fts5(title, body)
                """)
                )
                await conn.execute(
                    text("""
                    INSERT INTO entries_fts(rowid, title, body)
                    SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0
                """)
                )
            else:
                # Verify integrity — try a simple query
                try:
                    count = int(
                        (await conn.execute(text("SELECT COUNT(*) FROM entries_fts"))).scalar() or 0
                    )
                    entry_count = int(
                        (
                            await conn.execute(
                                text("SELECT COUNT(*) FROM entries WHERE is_deleted = 0")
                            )
                        ).scalar()
                        or 0
                    )
                    if count < entry_count:
                        logger.info("FTS index stale (%d/%d rows), rebuilding...", count, entry_count)
                        await conn.execute(text("DELETE FROM entries_fts"))
                        await conn.execute(
                            text("""
                            INSERT INTO entries_fts(rowid, title, body)
                            SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0
                        """)
                        )
                except Exception:
                    logger.warning("FTS index corrupt, rebuilding...")
                    try:
                        for name in ("fts_entry_ai", "fts_entry_au", "fts_entry_ad", "fts_entry_soft_del"):
                            await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                        await conn.execute(text("DROP TABLE IF EXISTS entries_fts"))
                        await conn.execute(
                            text("""
                            CREATE VIRTUAL TABLE entries_fts
                            USING fts5(title, body)
                        """)
                        )
                        await conn.execute(
                            text("""
                            INSERT INTO entries_fts(rowid, title, body)
                            SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0
                        """)
                        )
                    except Exception:
                        logger.warning("FTS5 rebuild failed — full-text search unavailable", exc_info=True)

            # Ensure triggers exist (DROP + CREATE for idempotency)
            # Skip if FTS5 table couldn't be created
            fts_exists = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
                )
            ).scalar()
            if fts_exists:
                for name in ("fts_entry_ai", "fts_entry_au", "fts_entry_ad", "fts_entry_soft_del"):
                    await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))

                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_ai AFTER INSERT ON entries
                    BEGIN
                        INSERT INTO entries_fts(rowid, title, body)
                        VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_au AFTER UPDATE ON entries
                    BEGIN
                        UPDATE entries_fts SET title = COALESCE(NEW.title, ''), body = NEW.body
                        WHERE rowid = NEW.id;
                    END
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_ad AFTER DELETE ON entries
                    BEGIN
                        INSERT INTO entries_fts(entries_fts, rowid, title, body)
                        VALUES ('delete', OLD.id, COALESCE(OLD.title, ''), OLD.body);
                    END
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_soft_del AFTER UPDATE ON entries
                    WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
                    BEGIN
                        INSERT INTO entries_fts(entries_fts, rowid, title, body)
                        VALUES ('delete', NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
    except Exception:
        logger.warning("FTS5 setup failed — full-text search unavailable", exc_info=True)


async def _seed_builtin_templates() -> None:
    from sqlalchemy import select

    from app.models.template import Template

    async with async_session() as session:
        # Use lightweight COUNT instead of loading ORM objects
        count = (
            await session.execute(
                select(func.count()).select_from(Template).where(Template.is_builtin.is_(True))
            )
        ).scalar() or 0
        if count > 0:
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
