"""SQLAlchemy async engine, session factory, and Base declarative model."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import create_engine, event, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_engine() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
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
    """Tune SQLite for a local single-writer app: WAL + fast, safe sync.

    WAL enables concurrent readers during writes. ``synchronous=NORMAL`` is safe
    under WAL (no corruption on an app crash; only the last commit is at risk on
    an OS-level power loss) and far faster at committing than the default FULL.
    The cache/temp pragmas keep hot pages and temp tables in RAM.
    """
    cursor = dbapi_conn.cursor()
    # auto_vacuum must be set BEFORE journal_mode=WAL, which creates the DB file
    # and would otherwise lock auto_vacuum to its default (NONE).
    cursor.execute("PRAGMA auto_vacuum = INCREMENTAL")  # enable free-page reclamation (see _ensure_incremental_vacuum)
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-4000")  # ~4 MiB page cache (tuned for single-user desktop reads)
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA wal_autocheckpoint=1000")  # flush WAL every ~4 MiB so -wal stays bounded
    cursor.close()


_engine_lock = asyncio.Lock()

engine, async_session = _build_engine()


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session per request with automatic rollback on error.

    The session factory is read off the module global without a lock: the read
    is atomic under the GIL, and ``reinit_engine`` swaps the global *before*
    draining the old engine so in-flight requests on the old factory keep
    working. (A lock here serialised every request for no benefit.)
    """
    session = async_session()
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
                raise RuntimeError(f"SQLite integrity check failed: {row}")

    # 3. Verify FTS5 is available (soft check — warn, don't abort)
    _fts5_available = False
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)"))
            await conn.execute(text("DROP TABLE IF EXISTS _fts5_check"))
            _fts5_available = True
        except Exception as exc:
            logger.warning(
                "SQLite FTS5 extension is not available: %s. Full-text search will not work.",
                exc,
            )

    logger.info("Database health check passed")


def _vacuum_sync(sync_url: str) -> bool:
    """Convert a ``NONE``/``FULL`` database to ``auto_vacuum = INCREMENTAL``.

    Uses a short-lived dedicated sync engine: ``VACUUM`` can't run in a
    transaction, and mixing sync connections into the async engine's aiosqlite
    pool leaks them. ``auto_vacuum`` only takes effect when the DB is (re)built,
    so a legacy DB needs a one-time ``VACUUM``. Returns True iff a reformat ran.
    Idempotent: once auto_vacuum is INCREMENTAL (==2) this is a no-op.
    """
    sync_eng = create_engine(sync_url)
    try:
        with sync_eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            mode = conn.execute(text("PRAGMA auto_vacuum")).scalar()
            if mode == 2:
                return False
            logger.info("Converting database to incremental auto_vacuum (one-time VACUUM)...")
            conn.execute(text("PRAGMA auto_vacuum = INCREMENTAL"))
            conn.execute(text("VACUUM"))
            return True
    finally:
        sync_eng.dispose()


async def _ensure_incremental_vacuum() -> None:
    """Enable incremental vacuum on an existing DB (one-time reformat), off the event loop."""
    await asyncio.to_thread(_vacuum_sync, f"sqlite:///{settings.db_path}")


async def init_db() -> None:
    """Create all tables (for dev/bootstrap; desktop uses inline migrations)."""
    # Enforce the SECRET_KEY guard for any *server* (non-desktop) deployment.
    # Desktop/Tauri sidecar runs locally with no external access and sets
    # DATA_DIR, so we skip validation there. Tying the guard to the production
    # env (rather than the presence of DATA_DIR) ensures a misconfigured server
    # that forgot DATA_DIR still fails fast.
    import os

    is_desktop_sidecar = bool(os.environ.get("DATA_DIR"))
    if settings.is_production and not is_desktop_sidecar:
        settings.validate_production()

    await validate_db_health()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)

    # One-time: convert a legacy DB to incremental auto_vacuum so the scheduled
    # maintenance job can reclaim free pages. Desktop sidecar only — avoid a
    # surprise startup VACUUM on server deployments.
    if is_desktop_sidecar:
        await _ensure_incremental_vacuum()

    # Ensure FTS5 virtual table and sync triggers exist.
    # The bundled stdlib sqlite3 in some PyInstaller builds mishandles
    # qualified column names (e.g. "entries.title"); we swap in pysqlite3
    # at import time (see app/main.py) to fix that, so FTS setup is safe in
    # frozen builds too.
    await _setup_fts()

    # Seed built-in templates (idempotent)
    await _seed_builtin_templates()


# Lightweight column migrations for desktop (no Alembic).
# Each entry: (table, column, sql). Safe to run on every startup — skipped if column exists.
_COLUMN_MIGRATIONS = [
    ("backup_config", "label", "ALTER TABLE backup_config ADD COLUMN label VARCHAR"),
    (
        "backup_snapshots",
        "backup_filename",
        "ALTER TABLE backup_snapshots ADD COLUMN backup_filename VARCHAR",
    ),
    ("entries", "summary", "ALTER TABLE entries ADD COLUMN summary VARCHAR(500)"),
    ("entries", "title", "ALTER TABLE entries ADD COLUMN title VARCHAR(255)"),
    ("entries", "mood", "ALTER TABLE entries ADD COLUMN mood VARCHAR(50)"),
    ("entries", "deleted_at", "ALTER TABLE entries ADD COLUMN deleted_at DATETIME"),
    ("entries", "encrypted_at", "ALTER TABLE entries ADD COLUMN encrypted_at DATETIME"),
    ("entries", "latitude", "ALTER TABLE entries ADD COLUMN latitude FLOAT"),
    ("entries", "longitude", "ALTER TABLE entries ADD COLUMN longitude FLOAT"),
    ("entries", "location_name", "ALTER TABLE entries ADD COLUMN location_name VARCHAR(255)"),
    (
        "entries",
        "created_at",
        "ALTER TABLE entries ADD COLUMN created_at DATETIME DEFAULT '1970-01-01 00:00:00'",
    ),
    (
        "entries",
        "updated_at",
        "ALTER TABLE entries ADD COLUMN updated_at DATETIME DEFAULT '1970-01-01 00:00:00'",
    ),
    # voice_recordings: legacy transcription columns. Older databases already
    # have these (is_transcribed is NOT NULL there); databases created after
    # transcription was removed lack them. Add if missing so every DB converges
    # to the same shape. Without this, recording INSERTs fail on old DBs
    # (NOT NULL, no default) and SELECTs fail on new DBs once the model declares
    # the column. Idempotent — skipped when the column already exists.
    (
        "voice_recordings",
        "is_transcribed",
        "ALTER TABLE voice_recordings ADD COLUMN is_transcribed BOOLEAN NOT NULL DEFAULT 0",
    ),
    (
        "voice_recordings",
        "transcription",
        "ALTER TABLE voice_recordings ADD COLUMN transcription VARCHAR",
    ),
    # Contacts — EPIM-style rich fields. Scalar extras + JSON multi-value lists.
    ("contacts", "nickname", "ALTER TABLE contacts ADD COLUMN nickname VARCHAR"),
    ("contacts", "department", "ALTER TABLE contacts ADD COLUMN department VARCHAR"),
    ("contacts", "profession", "ALTER TABLE contacts ADD COLUMN profession VARCHAR"),
    (
        "contacts",
        "is_favorite",
        "ALTER TABLE contacts ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0",
    ),
    ("contacts", "phones", "ALTER TABLE contacts ADD COLUMN phones JSON"),
    ("contacts", "addresses", "ALTER TABLE contacts ADD COLUMN addresses JSON"),
    ("contacts", "im_handles", "ALTER TABLE contacts ADD COLUMN im_handles JSON"),
    ("contacts", "websites", "ALTER TABLE contacts ADD COLUMN websites JSON"),
    ("contacts", "dates", "ALTER TABLE contacts ADD COLUMN dates JSON"),
    ("contacts", "relationships", "ALTER TABLE contacts ADD COLUMN relationships JSON"),
    # Email messages — local spam filter columns.
    (
        "email_messages",
        "is_spam",
        "ALTER TABLE email_messages ADD COLUMN is_spam BOOLEAN NOT NULL DEFAULT 0",
    ),
    ("email_messages", "spam_score", "ALTER TABLE email_messages ADD COLUMN spam_score FLOAT"),
    (
        "email_messages",
        "spam_user_override",
        "ALTER TABLE email_messages ADD COLUMN spam_user_override BOOLEAN",
    ),
    # Spam blocklist — what to do with mail from a blocked sender.
    (
        "spam_blocklist",
        "action",
        "ALTER TABLE spam_blocklist ADD COLUMN action VARCHAR(20) NOT NULL DEFAULT 'junk'",
    ),
    # Encryption — random per-entry/per-note PBKDF2 salt (null on legacy rows).
    (
        "entries",
        "encryption_salt",
        "ALTER TABLE entries ADD COLUMN encryption_salt VARCHAR(64)",
    ),
    (
        "notes",
        "encryption_salt",
        "ALTER TABLE notes ADD COLUMN encryption_salt VARCHAR(64)",
    ),
    # ── Google Calendar/Tasks sync provenance on calendar + task entities ──
    (
        "schedule_events",
        "external_id",
        "ALTER TABLE schedule_events ADD COLUMN external_id VARCHAR(255)",
    ),
    (
        "schedule_events",
        "external_calendar_id",
        "ALTER TABLE schedule_events ADD COLUMN external_calendar_id VARCHAR(255)",
    ),
    (
        "schedule_events",
        "source",
        "ALTER TABLE schedule_events ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'manual'",
    ),
    ("schedule_events", "etag", "ALTER TABLE schedule_events ADD COLUMN etag VARCHAR(255)"),
    ("schedule_events", "synced_at", "ALTER TABLE schedule_events ADD COLUMN synced_at DATETIME"),
    ("tasks", "external_id", "ALTER TABLE tasks ADD COLUMN external_id VARCHAR(255)"),
    (
        "tasks",
        "source",
        "ALTER TABLE tasks ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'manual'",
    ),
    ("tasks", "etag", "ALTER TABLE tasks ADD COLUMN etag VARCHAR(255)"),
    ("tasks", "synced_at", "ALTER TABLE tasks ADD COLUMN synced_at DATETIME"),
    ("task_lists", "external_id", "ALTER TABLE task_lists ADD COLUMN external_id VARCHAR(255)"),
    (
        "task_lists",
        "source",
        "ALTER TABLE task_lists ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'manual'",
    ),
    ("task_lists", "etag", "ALTER TABLE task_lists ADD COLUMN etag VARCHAR(255)"),
    ("task_lists", "synced_at", "ALTER TABLE task_lists ADD COLUMN synced_at DATETIME"),
]

_INDEX_MIGRATIONS = [
    (
        "ix_entries_deleted_date",
        "CREATE INDEX IF NOT EXISTS ix_entries_deleted_date ON entries (is_deleted, entry_date)",
    ),
    (
        "ix_entries_deleted_mood",
        "CREATE INDEX IF NOT EXISTS ix_entries_deleted_mood ON entries (is_deleted, mood)",
    ),
    (
        "ix_entry_tags_tag_id",
        "CREATE INDEX IF NOT EXISTS ix_entry_tags_tag_id ON entry_tags (tag_id)",
    ),
    # Notes (also model-declared; listed for parity with entries + idempotent safety).
    (
        "ix_notes_folder_pinned_updated",
        "CREATE INDEX IF NOT EXISTS ix_notes_folder_pinned_updated ON notes (is_deleted, folder_id, is_pinned, updated_at)",
    ),
    (
        "ix_notes_deleted_updated",
        "CREATE INDEX IF NOT EXISTS ix_notes_deleted_updated ON notes (is_deleted, updated_at)",
    ),
    ("ix_note_tags_tag_id", "CREATE INDEX IF NOT EXISTS ix_note_tags_tag_id ON note_tags (tag_id)"),
    (
        "ix_note_folders_deleted",
        "CREATE INDEX IF NOT EXISTS ix_note_folders_deleted ON note_folders (is_deleted)",
    ),
    # Google sync upsert lookups (find a local row by its Google resource id).
    (
        "ix_schedule_events_source_external",
        "CREATE INDEX IF NOT EXISTS ix_schedule_events_source_external "
        "ON schedule_events (source, external_id)",
    ),
    (
        "ix_tasks_source_external",
        "CREATE INDEX IF NOT EXISTS ix_tasks_source_external ON tasks (source, external_id)",
    ),
    (
        "ix_task_lists_source_external",
        "CREATE INDEX IF NOT EXISTS ix_task_lists_source_external "
        "ON task_lists (source, external_id)",
    ),
]


async def _migrate_schema(conn: Any) -> None:
    """Add missing columns and indexes to existing tables (idempotent).

    This is the **canonical** desktop/lightweight migration path: LifeLogr runs
    on SQLite in embedded (Tauri sidecar) mode where a single-process startup
    must self-heal its schema without an external tool. Add new columns here as
    ``(table, column, ALTER)`` tuples and new indexes to ``_INDEX_MIGRATIONS``;
    both lists are idempotent (skipped if the object already exists). A full
    Alembic setup was removed to avoid drift between two competing systems.
    """
    for table, column, sql in _COLUMN_MIGRATIONS:
        existing = {
            row[1] for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        }
        if column not in existing:
            logger.info("Adding column %s.%s ...", table, column)
            await conn.execute(text(sql))

    # entries.template_id (FK -> templates.id). Handled outside
    # _COLUMN_MIGRATIONS so the one-time content-match backfill runs atomically
    # with the column's first creation — and never again on later startups.
    entries_cols = {
        row[1] for row in (await conn.execute(text("PRAGMA table_info(entries)"))).fetchall()
    }
    if "template_id" not in entries_cols:
        logger.info("Adding column entries.template_id ...")
        await conn.execute(text("ALTER TABLE entries ADD COLUMN template_id INTEGER NULL"))
        await _backfill_entry_templates(conn)

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


async def _backfill_entry_templates(conn: Any) -> None:
    """One-time best-effort link of existing entries to a template.

    Assigns ``template_id`` to entries whose body starts with a template's body
    — the signature of "created from this template". Runs only when
    ``entries.template_id`` is first added. Longest template bodies are tried
    first so a specific template wins over a shorter/prefix one; template
    bodies shorter than 15 chars are ignored to avoid matching everything.
    """
    min_body = 15
    templates = (await conn.execute(text("SELECT id, body FROM templates"))).fetchall()
    candidates = [(row[0], row[1]) for row in templates if len((row[1] or "").strip()) >= min_body]
    candidates.sort(key=lambda item: len(item[1]), reverse=True)  # most specific first
    if not candidates:
        return

    rows = (await conn.execute(text("SELECT id, body FROM entries"))).fetchall()
    for entry_id, body in rows:
        if not body:
            continue
        for template_id, template_body in candidates:
            if body.startswith(template_body):
                await conn.execute(
                    text("UPDATE entries SET template_id = :tid WHERE id = :eid"),
                    {"tid": template_id, "eid": entry_id},
                )
                break
    logger.info("Backfilled entries.template_id by content match.")


# Bump to force a one-time rebuild of the FTS5 index on every existing database
# (tracked via ``PRAGMA user_version``). Needed because the FTS5 ``'delete'``
# sync command requires the supplied column values to *exactly* match the row in
# the index — once the index drifts out of sync with ``entries`` (a historical
# issue), every ``UPDATE entries`` (soft-delete, edits, AI enrichment) fails with
# "SQL logic error". A clean rebuild re-aligns the index so the sync triggers
# keep it consistent from then on.
_FTS_REBUILD_VERSION = 2


async def _setup_fts() -> None:
    """Create FTS5 virtual table if missing, populate, and install sync triggers."""
    try:
        async with engine.begin() as conn:
            exists = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
                )
            ).scalar()
            user_version = int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
            force_rebuild = user_version < _FTS_REBUILD_VERSION

            if not exists or force_rebuild:
                # Fresh index, or a one-time forced rebuild to self-heal drift.
                if force_rebuild and exists:
                    logger.info(
                        "Forcing FTS5 rebuild (user_version %d < %d) to heal index drift...",
                        user_version,
                        _FTS_REBUILD_VERSION,
                    )
                else:
                    logger.info("Creating FTS5 index and populating...")
                # Drop sync triggers + table so repopulation starts clean.
                for name in (
                    "fts_entry_ai",
                    "fts_entry_au",
                    "fts_entry_ad",
                    "fts_entry_soft_del",
                    "fts_entry_restore",
                ):
                    await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                await conn.execute(text("DROP TABLE IF EXISTS entries_fts"))
                await conn.execute(text("CREATE VIRTUAL TABLE entries_fts USING fts5(title, body)"))
                await conn.execute(
                    text("""
                    INSERT INTO entries_fts(rowid, title, body)
                    SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0 AND entries.is_encrypted = 0
                """)
                )
                if force_rebuild:
                    await conn.execute(text(f"PRAGMA user_version = {_FTS_REBUILD_VERSION}"))
            else:
                # Index exists and is at the current rebuild version — verify it
                # isn't missing/extra rows (cheap), rebuild if so.
                try:
                    count = int(
                        (await conn.execute(text("SELECT COUNT(*) FROM entries_fts"))).scalar() or 0
                    )
                    entry_count = int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT COUNT(*) FROM entries WHERE is_deleted = 0 AND is_encrypted = 0"
                                )
                            )
                        ).scalar()
                        or 0
                    )
                    if count != entry_count:
                        logger.info(
                            "FTS index stale (%d/%d rows), rebuilding...", count, entry_count
                        )
                        await conn.execute(text("DELETE FROM entries_fts"))
                        await conn.execute(
                            text("""
                            INSERT INTO entries_fts(rowid, title, body)
                            SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0 AND entries.is_encrypted = 0
                        """)
                        )
                except Exception:
                    logger.warning("FTS index corrupt, rebuilding...")
                    try:
                        for name in (
                            "fts_entry_ai",
                            "fts_entry_au",
                            "fts_entry_ad",
                            "fts_entry_soft_del",
                            "fts_entry_restore",
                        ):
                            await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                        await conn.execute(text("DROP TABLE IF EXISTS entries_fts"))
                        await conn.execute(
                            text("CREATE VIRTUAL TABLE entries_fts USING fts5(title, body)")
                        )
                        await conn.execute(
                            text("""
                            INSERT INTO entries_fts(rowid, title, body)
                            SELECT entries.id, COALESCE(entries.title, ''), entries.body FROM entries WHERE entries.is_deleted = 0 AND entries.is_encrypted = 0
                        """)
                        )
                    except Exception:
                        logger.warning(
                            "FTS5 rebuild failed — full-text search unavailable", exc_info=True
                        )

            # Ensure triggers exist (DROP + CREATE for idempotency)
            # Skip if FTS5 table couldn't be created
            fts_exists = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
                )
            ).scalar()
            if fts_exists:
                for name in (
                    "fts_entry_ai",
                    "fts_entry_au",
                    "fts_entry_ad",
                    "fts_entry_soft_del",
                    "fts_entry_restore",
                    "fts_entry_encrypt",
                    "fts_entry_decrypt",
                ):
                    await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))

                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_ai AFTER INSERT ON entries
                    WHEN NEW.is_deleted = 0 AND NEW.is_encrypted = 0
                    BEGIN
                        INSERT INTO entries_fts(rowid, title, body)
                        VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
                # Remove+reinsert (not UPDATE) so this is correct even when the
                # row was previously removed from FTS (e.g. after a soft delete
                # followed by content edits) — a plain UPDATE would be a no-op.
                # Only re-index plaintext→plaintext edits of non-encrypted rows;
                # encryption/decryption transitions are handled by dedicated
                # triggers below so ciphertext is never indexed.
                #
                # NOTE: we use ``DELETE FROM entries_fts WHERE rowid = ...`` rather
                # than the FTS5 ``'delete'`` command (``INSERT INTO ft(ft,...)
                # VALUES('delete',...)``). The latter throws "SQL logic error" in
                # the bundled SQLite/pysqlite3 build, which would fail every
                # ``UPDATE entries`` (edits, soft-delete, AI enrichment).
                # DELETE-by-rowid is equivalent and works reliably.
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_au AFTER UPDATE ON entries
                    WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 0
                       AND NEW.is_encrypted = 0 AND OLD.is_encrypted = 0
                    BEGIN
                        DELETE FROM entries_fts WHERE rowid = NEW.id;
                        INSERT INTO entries_fts(rowid, title, body)
                        VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_ad AFTER DELETE ON entries
                    BEGIN
                        DELETE FROM entries_fts WHERE rowid = OLD.id;
                    END
                """)
                )
                # Soft delete: remove from FTS index (0 → 1).
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_soft_del AFTER UPDATE ON entries
                    WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
                    BEGIN
                        DELETE FROM entries_fts WHERE rowid = NEW.id;
                    END
                """)
                )
                # Restore: re-index the entry (1 → 0). Skip encrypted entries —
                # their body column holds ciphertext, not searchable text.
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_restore AFTER UPDATE ON entries
                    WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 1 AND NEW.is_encrypted = 0
                    BEGIN
                        INSERT INTO entries_fts(rowid, title, body)
                        VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
                # Encryption toggle. Encrypted entries must never live in the
                # search index: on encrypt, drop the now-stale plaintext row; on
                # decrypt, re-index the restored plaintext body.
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_encrypt AFTER UPDATE ON entries
                    WHEN NEW.is_encrypted = 1 AND OLD.is_encrypted = 0
                    BEGIN
                        DELETE FROM entries_fts WHERE rowid = NEW.id;
                    END
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TRIGGER fts_entry_decrypt AFTER UPDATE ON entries
                    WHEN NEW.is_encrypted = 0 AND OLD.is_encrypted = 1 AND NEW.is_deleted = 0
                    BEGIN
                        DELETE FROM entries_fts WHERE rowid = NEW.id;
                        INSERT INTO entries_fts(rowid, title, body)
                        VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                    END
                """)
                )
    except Exception:
        logger.warning("FTS5 setup failed — full-text search unavailable", exc_info=True)

    # Notes FTS — mirrors the entries block but simpler: notes_fts is a fresh
    # table with no historical drift to heal, so a clean create-once + trigger
    # install is enough. Isolated in its own try/except so a notes FTS failure
    # can never break the entries index.
    try:
        async with engine.begin() as conn:
            exists = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'")
                )
            ).scalar()
            if not exists:
                logger.info("Creating notes FTS index and populating...")
                await conn.execute(text("CREATE VIRTUAL TABLE notes_fts USING fts5(title, body)"))
                await conn.execute(
                    text("""
                    INSERT INTO notes_fts(rowid, title, body)
                    SELECT notes.id, COALESCE(notes.title, ''), notes.body FROM notes WHERE notes.is_deleted = 0 AND notes.is_encrypted = 0
                """)
                )

            # Triggers (DROP + CREATE for idempotency). Same conventions as the
            # entries triggers: UPDATE does DELETE-by-rowid then INSERT (NOT the
            # FTS5 'delete' command, which throws in bundled pysqlite3).
            for name in (
                "fts_note_ai",
                "fts_note_au",
                "fts_note_ad",
                "fts_note_soft_del",
                "fts_note_restore",
                "fts_note_encrypt",
                "fts_note_decrypt",
            ):
                await conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))

            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_ai AFTER INSERT ON notes
                WHEN NEW.is_deleted = 0 AND NEW.is_encrypted = 0
                BEGIN
                    INSERT INTO notes_fts(rowid, title, body)
                    VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                END
            """)
            )
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_au AFTER UPDATE ON notes
                WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 0
                   AND NEW.is_encrypted = 0 AND OLD.is_encrypted = 0
                BEGIN
                    DELETE FROM notes_fts WHERE rowid = NEW.id;
                    INSERT INTO notes_fts(rowid, title, body)
                    VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                END
            """)
            )
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_ad AFTER DELETE ON notes
                BEGIN
                    DELETE FROM notes_fts WHERE rowid = OLD.id;
                END
            """)
            )
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_soft_del AFTER UPDATE ON notes
                WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
                BEGIN
                    DELETE FROM notes_fts WHERE rowid = NEW.id;
                END
            """)
            )
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_restore AFTER UPDATE ON notes
                WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 1 AND NEW.is_encrypted = 0
                BEGIN
                    INSERT INTO notes_fts(rowid, title, body)
                    VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                END
            """)
            )
            # Encryption toggle: never index ciphertext notes.
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_encrypt AFTER UPDATE ON notes
                WHEN NEW.is_encrypted = 1 AND OLD.is_encrypted = 0
                BEGIN
                    DELETE FROM notes_fts WHERE rowid = NEW.id;
                END
            """)
            )
            await conn.execute(
                text("""
                CREATE TRIGGER fts_note_decrypt AFTER UPDATE ON notes
                WHEN NEW.is_encrypted = 0 AND OLD.is_encrypted = 1 AND NEW.is_deleted = 0
                BEGIN
                    DELETE FROM notes_fts WHERE rowid = NEW.id;
                    INSERT INTO notes_fts(rowid, title, body)
                    VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
                END
            """)
            )
    except Exception:
        logger.warning(
            "Notes FTS5 setup failed — notes full-text search unavailable", exc_info=True
        )


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
