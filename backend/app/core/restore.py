"""Shared atomic restore utility for backup import/restore operations.

Guarantees:
  1. Validates the extracted database before any swap.
  2. Backs up both DB and media before touching anything.
  3. Uses atomic file swaps (os.rename on same FS).
  4. Full rollback on any failure — if media restore fails after DB succeeds,
     the DB is rolled back too.
  5. WAL checkpoint before backup; abort if checkpoint fails.
"""

import logging
import os
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SQLITE_HEADER = b"SQLite format 3\x00"
_EXPECTED_TABLES = {"entries"}


def _is_sqlite_file(path: Path) -> bool:
    """Quick check that *path* starts with the SQLite magic header."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == _SQLITE_HEADER
    except OSError:
        return False


def _check_integrity(db_path: Path) -> None:
    """Run ``PRAGMA integrity_check`` on *db_path* via synchronous sqlite3."""
    conn = sqlite3.connect(str(db_path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise ValueError(f"SQLite integrity check failed: {result[0]}")
    finally:
        conn.close()


def _check_expected_tables(db_path: Path) -> None:
    """Verify that at least the ``entries`` table exists."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = _EXPECTED_TABLES - tables
        if missing:
            raise ValueError(f"Database missing expected tables: {missing}")
    finally:
        conn.close()


async def checkpoint_wal(db_path: Path) -> None:
    """Checkpoint the WAL for *db_path*.  Raises on failure.

    Uses the async engine so the same aiosqlite connection pool is used.
    """
    from sqlalchemy import text

    from app.core.database import engine

    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        row = result.fetchone()
        if row is None:
            raise RuntimeError("WAL checkpoint returned no result row")
        # row: (busy, log, checkpointed) — busy != 0 means the checkpoint
        # could not complete because readers are still active.
        if row[0] != 0:
            raise RuntimeError(
                f"WAL checkpoint failed (busy={row[0]}, log={row[1]}, "
                f"checkpointed={row[2]}). Retry when the database is idle."
            )


async def _checkpoint_live(
    live_db: Path, session: AsyncSession | None = None
) -> None:
    """Best-effort WAL checkpoint of the live DB before a restore/swap.

    Prefers the caller's *session* connection so we don't open a second pooled
    connection — SQLite's engine pool is size 1, so doing so from a request
    that already holds the session would deadlock (``QueuePool limit reached``).
    Tolerant of "busy": the live DB is backed up before the swap and the file
    is replaced regardless, so a checkpoint that can't fully TRUNCATE is fine.
    """
    from sqlalchemy import text

    from app.core.database import engine

    try:
        if session is not None:
            await session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        else:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        logger.warning("WAL checkpoint before restore failed (continuing)", exc_info=True)


def validate_extracted_db(db_path: Path) -> None:
    """Validate a database file before swapping it in.

    Checks: SQLite header, ``PRAGMA integrity_check``, expected tables.
    Raises ``ValueError`` on any failure.
    """
    if not db_path.exists():
        raise ValueError(f"Extracted database not found: {db_path}")
    if db_path.stat().st_size == 0:
        raise ValueError("Extracted database is empty (0 bytes)")
    if not _is_sqlite_file(db_path):
        raise ValueError(
            "Extracted file is not a valid SQLite database (bad header)"
        )
    _check_integrity(db_path)
    _check_expected_tables(db_path)
    logger.info("Extracted database validated: %s", db_path)


def _atomic_write(src: Path, dst: Path) -> None:
    """Write *src* to *dst* atomically via a .tmp file + os.rename."""
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copy2(str(src), str(tmp))
        os.replace(str(tmp), str(dst))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_media_swap(src: Path, dst: Path) -> None:
    """Replace *dst* directory with *src* atomically.

    Renames existing to .bak, copies new in, removes .bak on success.
    """
    bak = dst.with_name(dst.name + ".bak")
    # Remove stale backup if present
    if bak.exists():
        shutil.rmtree(str(bak), ignore_errors=True)

    if dst.exists():
        os.rename(str(dst), str(bak))

    try:
        shutil.copytree(str(src), str(dst))
    except BaseException:
        # Roll back
        if bak.exists():
            if dst.exists():
                shutil.rmtree(str(dst), ignore_errors=True)
            os.rename(str(bak), str(dst))
        raise
    else:
        # Success — remove backup
        shutil.rmtree(str(bak), ignore_errors=True)


async def atomic_restore(
    extracted_db: Path,
    extracted_media: Path | None,
    live_db: Path,
    live_media: Path,
    session: AsyncSession | None = None,
) -> list[str]:
    """Atomically restore database and (optionally) media files.

    1. Validate extracted DB (header, integrity, tables).
    2. Checkpoint live WAL.
    3. Back up live DB to ``<live_db>.pre-restore.bak``.
    4. Swap DB atomically (tmp + os.replace).
    5. If *extracted_media* exists, swap media atomically.
    6. On media failure after DB success, roll DB back too.
    7. Clean up backup files on success.

    *session* (when the caller is a request holding one) lets the checkpoint
    reuse that connection instead of opening a second pooled one (deadlock on
    SQLite's size-1 pool).
    """
    from app.core.database import init_db, reinit_engine

    restored: list[str] = []

    # ── Validate ──────────────────────────────────────────────────────────
    validate_extracted_db(extracted_db)

    # ── Checkpoint live WAL ───────────────────────────────────────────────
    if live_db.exists():
        await _checkpoint_live(live_db, session)

    # ── Backup live DB ────────────────────────────────────────────────────
    db_backup = live_db.with_suffix(live_db.suffix + ".pre-restore.bak")
    if live_db.exists():
        shutil.copy2(str(live_db), str(db_backup))

    # ── Swap DB ───────────────────────────────────────────────────────────
    await reinit_engine()  # release file handles
    db_swapped = False
    try:
        _atomic_write(extracted_db, live_db)
        await init_db()
        restored.append("database")
        db_swapped = True
    except BaseException:
        logger.error("Database restore failed, rolling back", exc_info=True)
        if db_backup.exists():
            _atomic_write(db_backup, live_db)
        db_backup.unlink(missing_ok=True)
        raise

    # ── Swap media ────────────────────────────────────────────────────────
    if extracted_media is not None and extracted_media.exists():
        try:
            _atomic_media_swap(extracted_media, live_media)
            restored.append("media")
        except BaseException:
            # Media failed — roll back the DB too
            logger.error(
                "Media restore failed, rolling back database too", exc_info=True
            )
            if db_swapped and db_backup.exists():
                await reinit_engine()
                _atomic_write(db_backup, live_db)
                await init_db()
            db_backup.unlink(missing_ok=True)
            raise

    # ── Success — clean up backup ─────────────────────────────────────────
    db_backup.unlink(missing_ok=True)
    return restored
