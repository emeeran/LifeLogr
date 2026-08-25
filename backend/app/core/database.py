"""SQLAlchemy async engine, session factory, and Base declarative model."""

import asyncio
import logging
import shutil
import sqlite3
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
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
        # SQLite runs in WAL mode with busy_timeout (see _set_sqlite_pragma), so
        # a normal-sized pool is safe and prevents long background jobs (email
        # sync, backup) from starving reads. Hardcoding size 1/overflow 0 made
        # any long DB session freeze the whole app (the "entries missing" bug).
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
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
    # auto_vacuum is a persistent DB-level setting. Only SET it (which acquires
    # the write lock) when it isn't already INCREMENTAL — otherwise every new
    # pooled connection contends for the write lock on connect and the app sees
    # "database is locked" under concurrent load. Must run before journal_mode=WAL,
    # which creates the DB file and would lock auto_vacuum to its default (NONE).
    # pysqlite3's cursor.execute() returns None (unlike stdlib sqlite3, which
    # returns the cursor), so call fetchone() on the cursor directly — don't chain.
    cursor.execute("PRAGMA auto_vacuum")
    if cursor.fetchone()[0] != 2:  # 2 = INCREMENTAL
        cursor.execute("PRAGMA auto_vacuum = INCREMENTAL")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute(
        "PRAGMA cache_size=-4000"
    )  # ~4 MiB page cache (tuned for single-user desktop reads)
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


# ── Boot-time DB safety snapshot + integrity recovery ─────────────────────────
# A rotating in-place copy of lifelogr.db taken before any migration runs, so a
# botched migration, a crash mid-write, or an external tool is always recoverable
# from the last good boot. If the live file fails PRAGMA integrity_check at boot,
# the newest good snapshot is restored automatically instead of aborting to a
# dead app with no entries. All file work uses throwaway sync sqlite3 connections
# off the event loop (mirrors _vacuum_sync), so the async engine never observes a
# corrupt file and recovery is a safe file swap with no open transaction.
_BOOT_SNAPSHOT_PREFIX = "lifelogr.db.boot-bak-"
_CORRUPT_PREFIX = "lifelogr.db.corrupt-"
_BOOT_SNAPSHOT_RETENTION = 5


def _integrity_check_sync(db_path: Path) -> str:
    """Return ``PRAGMA integrity_check`` via a throwaway read-only connection.

    Uses ``sqlite3`` — pysqlite3 in frozen builds (swapped in ``app.main`` at
    import, before this module loads). pysqlite3's ``cursor.execute()`` returns
    ``None`` (unlike stdlib sqlite3 which returns the cursor), so ``fetchone()``
    is called on the cursor directly, never chained — same convention as
    ``_set_sqlite_pragma``.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            cur = conn.execute("PRAGMA integrity_check")
            return str(cur.fetchone()[0])
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        logger.warning("integrity_check could not run on %s: %s", db_path, exc)
        return f"unreadable: {exc}"


def _checkpoint_wal_sync(db_path: Path) -> bool:
    """Best-effort ``wal_checkpoint(TRUNCATE)`` on a throwaway connection.

    Mirrors ``scheduler_service._checkpoint_wal_robust`` but on a dedicated sync
    connection, so it is safe to run before ``init_db`` opens any pooled async
    connection. Returns False if the WAL stayed busy across retries (the snapshot
    then lags recent commits; the scheduled backup still bundles -wal/-shm).
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            for _ in range(5):
                cur = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                row = cur.fetchone()
                if row is None or row[0] == 0:
                    return True
            return False
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        logger.warning("WAL checkpoint (boot) failed for %s", db_path, exc_info=True)
        return False


def _create_boot_snapshot_sync(
    db_path: Path, data_dir: Path, retention: int = _BOOT_SNAPSHOT_RETENTION, _ts: str | None = None
) -> Path | None:
    """Checkpoint then copy the DB to ``data_dir/lifelogr.db.boot-bak-<ts>``; rotate.

    A plain ``.db`` copy (not tar+media): recovery must be bulletproof-simple and
    the snapshot itself must be directly ``integrity_check``-able. Rotates to the
    newest ``retention`` copies (mirrors ``scheduler_service._cleanup_old_backups``).
    ``_ts`` is injectable so tests can force distinct filenames (real boots are
    ≥1 s apart).
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    if not _checkpoint_wal_sync(db_path):
        logger.warning("Boot snapshot: WAL checkpoint busy; snapshot may lag recent commits.")
    ts = _ts or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snapshot = data_dir / f"{_BOOT_SNAPSHOT_PREFIX}{ts}"
    try:
        shutil.copy2(db_path, snapshot)
    except OSError:
        logger.warning("Boot snapshot could not be written to %s", snapshot, exc_info=True)
        return None
    # Rotate by the timestamp embedded in the filename (not mtime): copy2 carries
    # the source DB's mtime onto the snapshot, so two boots that share a DB mtime
    # would otherwise tie and prune in filesystem order. Names sort chronologically.
    snaps = sorted(data_dir.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"), key=lambda p: p.name)
    for old in snaps[: max(0, len(snaps) - retention)]:
        old.unlink(missing_ok=True)
    logger.info("Boot DB snapshot saved: %s", snapshot.name)
    return snapshot


def _recover_from_snapshot_sync(db_path: Path, data_dir: Path, _ts: str | None = None) -> bool:
    """Quarantine a corrupt DB and restore the newest good snapshot over it.

    The corrupt file is preserved as ``lifelogr.db.corrupt-<ts>`` for forensics —
    never silently destroyed. Restores only a snapshot whose own
    ``integrity_check == "ok"`` and clears stale ``-wal``/``-shm`` sidecars so
    SQLite starts clean from the restored main file. Returns True on a clean
    restore, False if no intact snapshot exists.
    """
    ts = _ts or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    corrupt = data_dir / f"{_CORRUPT_PREFIX}{ts}"
    try:
        shutil.copy2(db_path, corrupt)
        db_path.unlink(missing_ok=True)
        logger.error("DB integrity check failed — corrupt file quarantined as %s", corrupt.name)
    except OSError:
        logger.error("Could not quarantine corrupt DB %s", db_path, exc_info=True)
        return False

    snaps = sorted(data_dir.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"), key=lambda p: p.name, reverse=True)
    for snap in snaps:
        if _integrity_check_sync(snap) != "ok":
            continue
        try:
            shutil.copy2(snap, db_path)
        except OSError:
            logger.warning("Snapshot restore copy failed: %s", snap, exc_info=True)
            continue
        # Drop the corrupt DB's stale WAL sidecars so SQLite replays nothing old
        # onto the restored main file.
        for sidecar in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            sidecar.unlink(missing_ok=True)
        logger.info("DB recovered from snapshot %s", snap.name)
        return True
    logger.error("No intact boot snapshot available for recovery.")
    return False


def _preflight_db_file_sync(db_path: Path, data_dir: Path) -> None:
    """Snapshot + integrity-check the DB file before the async engine touches it.

    Snapshot only a healthy file (for next boot's recovery). If the live file is
    corrupt, recover from the newest good snapshot; if none exists, raise (the
    corrupt file is still quarantined). Raises ``RuntimeError`` only when the DB
    cannot be made healthy.
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return  # fresh DB — nothing to snapshot; create_all will build it.
    if _integrity_check_sync(db_path) == "ok":
        _create_boot_snapshot_sync(db_path, data_dir)
        return
    if not _recover_from_snapshot_sync(db_path, data_dir):
        raise RuntimeError(
            f"SQLite integrity check failed for {db_path} and no intact boot "
            f"snapshot was available for recovery. The corrupt file was "
            f"quarantined in {data_dir}."
        )
    if _integrity_check_sync(db_path) != "ok":
        raise RuntimeError(f"Database at {db_path} is still corrupt after snapshot recovery.")
    # Snapshot the restored file too so a good copy is always on hand.
    _create_boot_snapshot_sync(db_path, data_dir)


async def _preflight_db_file() -> None:
    """Preflight the DB file (snapshot + integrity + recover) off the event loop."""
    await asyncio.to_thread(_preflight_db_file_sync, settings.db_path, settings.DATA_DIR)


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

    # Desktop only: snapshot the DB file and verify its integrity BEFORE the async
    # engine opens a connection. If the live file is corrupt, recover from the
    # newest good boot snapshot so the engine never opens a damaged DB (the
    # documented "entries missing" failure mode). Runs off the event loop on
    # throwaway sync connections; recovery is a safe file swap with no open txn.
    if is_desktop_sidecar:
        await _preflight_db_file()

    await validate_db_health()

    # Ensure every ORM model is registered in Base.metadata before create_all —
    # some are only imported lazily inside service functions and would otherwise
    # be missing from create_all / schema introspection. (Lazy to avoid a
    # load-time cycle: models import Base from this module.)
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)
        await _drop_removed_feature_tables(conn)

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
]


async def _drop_removed_feature_tables(conn: Any) -> None:
    """Drop tables from removed or never-active features.

    Idempotent (``IF EXISTS``); child-first so inbound FKs don't block. Purges
    the data as part of removing these features. Safe to run on every boot.
    """
    for table in (
        # Email / Contacts / Tasks / Schedule / Google sync (recently removed)
        "email_attachments",
        "email_messages",
        "email_folders",
        "email_accounts",
        "spam_blocklist",
        "contact_group_members",
        "contact_groups",
        "contacts",
        "tasks",
        "task_lists",
        "schedule_events",
        "google_sync_account",
        # Older legacy tables — no ORM model, no active code path (verified unused)
        "alembic_version",
        "digests",
        "entry_revisions",
        "ocr_results",
        "plugin_hooks",
        "plugins",
    ):
        await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


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

    await _stamp_schema_version(conn)


# Bumped whenever a new column/index migration is added to _COLUMN_MIGRATIONS /
# _INDEX_MIGRATIONS. Stamped into ``_schema_meta`` only after a completed
# migration run, so a partial/crashed run stays detectable on the next startup
# (the previous, lower stamp remains; the idempotent migrations then re-run and
# heal). NOTE: ``PRAGMA user_version`` is reserved for FTS-index rebuild tracking.
_SCHEMA_VERSION = 1


async def _stamp_schema_version(conn: Any) -> None:
    """Record that the schema migration run reached the current version.

    Uses a small ``_schema_meta`` key/value table. Also appends a short auditable
    log of completed runs (capped to the last 10) so recoverability is visible.
    """
    import json
    from datetime import datetime, timezone

    await conn.execute(
        text("CREATE TABLE IF NOT EXISTS _schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    )
    prev = (
        await conn.execute(text("SELECT value FROM _schema_meta WHERE key='schema_version'"))
    ).scalar()
    prev_int = int(prev) if prev and str(prev).isdigit() else 0
    await conn.execute(
        text(
            "INSERT INTO _schema_meta(key, value) VALUES('schema_version', :v) "
            "ON CONFLICT(key) DO UPDATE SET value = :v"
        ),
        {"v": str(_SCHEMA_VERSION)},
    )
    log_row = (
        await conn.execute(text("SELECT value FROM _schema_meta WHERE key='migration_log'"))
    ).scalar()
    try:
        runs = json.loads(log_row) if log_row else []
    except (ValueError, TypeError):
        runs = []
    runs.append(
        {
            "from": prev_int,
            "to": _SCHEMA_VERSION,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    runs = runs[-10:]
    await conn.execute(
        text(
            "INSERT INTO _schema_meta(key, value) VALUES('migration_log', :v) "
            "ON CONFLICT(key) DO UPDATE SET value = :v"
        ),
        {"v": json.dumps(runs)},
    )
    logger.info("Schema migrations complete: version %d (was %d)", _SCHEMA_VERSION, prev_int)


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
            else:
                # Index exists — verify it isn't corrupt or stale; rebuild if so.
                try:
                    fts_n = int(
                        (await conn.execute(text("SELECT COUNT(*) FROM notes_fts"))).scalar() or 0
                    )
                    note_n = int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT COUNT(*) FROM notes WHERE is_deleted = 0 AND is_encrypted = 0"
                                )
                            )
                        ).scalar()
                        or 0
                    )
                    if fts_n != note_n:
                        logger.info(
                            "Notes FTS index stale (%d/%d rows), rebuilding...", fts_n, note_n
                        )
                        await conn.execute(text("DELETE FROM notes_fts"))
                        await conn.execute(
                            text("""
                                INSERT INTO notes_fts(rowid, title, body)
                                SELECT notes.id, COALESCE(notes.title, ''), notes.body FROM notes WHERE notes.is_deleted = 0 AND notes.is_encrypted = 0
                            """)
                        )
                except Exception:
                    logger.warning("Notes FTS index corrupt, rebuilding...", exc_info=True)
                    try:
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
                        await conn.execute(text("DROP TABLE IF EXISTS notes_fts"))
                        await conn.execute(
                            text("CREATE VIRTUAL TABLE notes_fts USING fts5(title, body)")
                        )
                        await conn.execute(
                            text("""
                                INSERT INTO notes_fts(rowid, title, body)
                                SELECT notes.id, COALESCE(notes.title, ''), notes.body FROM notes WHERE notes.is_deleted = 0 AND notes.is_encrypted = 0
                            """)
                        )
                    except Exception:
                        logger.warning(
                            "Notes FTS rebuild failed — notes search unavailable", exc_info=True
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


async def rebuild_search_index() -> dict[str, int]:
    """Repopulate the ``entries_fts`` / ``notes_fts`` indexes from base tables.

    Lightweight drift repair used by the startup integrity check (self-heal)
    and the Diagnostics "Rebuild search index" action: clears and re-inserts
    the indexable rows, leaving the FTS virtual tables and their triggers in
    place. Tables that don't yet exist are skipped (count 0). Idempotent.

    Uses the module ``async_session`` (not ``engine`` directly) so tests that
    repoint it at a temp DB are followed.
    """
    counts: dict[str, int] = {}
    async with async_session() as session:
        for fts, base in (("entries_fts", "entries"), ("notes_fts", "notes")):
            exists = (
                await session.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": fts}
                )
            ).scalar()
            if not exists:
                counts[base] = 0
                continue
            try:
                await session.execute(text(f"DELETE FROM {fts}"))
                await session.execute(
                    text(f"""
                        INSERT INTO {fts}(rowid, title, body)
                        SELECT {base}.id, COALESCE({base}.title, ''), {base}.body
                        FROM {base}
                        WHERE {base}.is_deleted = 0 AND {base}.is_encrypted = 0
                    """)
                )
                counts[base] = int(
                    (await session.execute(text(f"SELECT COUNT(*) FROM {fts}"))).scalar() or 0
                )
            except Exception:
                # Corrupt FTS table — full DROP+CREATE recovery happens at next
                # boot via _setup_fts; here we roll back so the *other* index can
                # still rebuild, and skip this one.
                await session.rollback()
                logger.warning(
                    "%s rebuild failed (may be corrupt); will recover on next boot",
                    fts,
                    exc_info=True,
                )
                counts[base] = 0
        await session.commit()
    logger.info("Search index rebuilt: %s", counts)
    return counts


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
