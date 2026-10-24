"""Shared atomic restore utility for backup import/restore operations.

Guarantees:
  1. Validates the extracted database before any swap.
  2. Backs up both DB and media before touching anything.
  3. Uses atomic file swaps (os.rename on same FS).
  4. Full rollback on any failure — if media restore fails after DB succeeds,
     the DB is rolled back too.
  5. WAL checkpoint before backup; abort if checkpoint fails.
  6. The live DB's stale ``-wal``/``-shm`` sidecars are removed around the
     swap, and an archive's own sidecars are only reinstalled when their
     headers say they really are SQLite WAL/wal-index files.
"""

import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SQLITE_HEADER = b"SQLite format 3\x00"
_EXPECTED_TABLES = {"entries"}

# A WAL file starts with a 4-byte big-endian magic (0x377f0682 / ...83, the
# latter for big-endian checksums) followed by its format version. A ``-shm``
# (wal-index) file starts with that same version in the *host's* byte order —
# the wal-index is machine-specific, unlike the WAL. Anything else is not a
# sidecar SQLite will accept, so a restore must not install it.
_WAL_MAGICS = (b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83")
_WAL_FORMAT_VERSION = 3007000
_WAL_INDEX_VERSIONS = (
    _WAL_FORMAT_VERSION.to_bytes(4, "little"),
    _WAL_FORMAT_VERSION.to_bytes(4, "big"),
)


def _is_sqlite_file(path: Path) -> bool:
    """Quick check that *path* starts with the SQLite magic header."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == _SQLITE_HEADER
    except OSError:
        return False


def _starts_with(path: Path, magic: tuple[bytes, ...] | bytes) -> bool:
    """True if *path* begins with any of *magic* (missing/unreadable → False)."""
    expected = magic if isinstance(magic, tuple) else (magic,)
    try:
        with open(path, "rb") as fh:
            head = fh.read(max(len(m) for m in expected))
    except OSError:
        return False
    return any(head.startswith(m) for m in expected)


def is_valid_wal_file(path: Path) -> bool:
    """True if *path* looks like a real SQLite write-ahead log."""
    return _starts_with(path, _WAL_MAGICS)


def is_valid_wal_index_file(path: Path) -> bool:
    """True if *path* looks like a real SQLite wal-index (``-shm``) file."""
    return _starts_with(path, _WAL_INDEX_VERSIONS)


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
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
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


async def _checkpoint_live(live_db: Path, session: AsyncSession | None = None) -> None:
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
        raise ValueError("Extracted file is not a valid SQLite database (bad header)")
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


class _SidecarPlan(NamedTuple):
    """Which of an archive's sidecars may be installed alongside the main file."""

    wal: Path | None
    shm: Path | None

    @property
    def any(self) -> bool:
        return self.wal is not None or self.shm is not None

    def destinations(self, db_path: Path) -> list[tuple[Path, Path]]:
        """(source, live destination) pairs, named ``<db>-wal``/``<db>-shm``."""
        pairs: list[tuple[Path, Path]] = []
        if self.wal is not None:
            pairs.append((self.wal, Path(f"{db_path}-wal")))
        if self.shm is not None:
            pairs.append((self.shm, Path(f"{db_path}-shm")))
        return pairs


def _plan_sidecars(
    extracted_db: Path, extracted_wal: Path | None, extracted_shm: Path | None
) -> _SidecarPlan:
    """Decide which archive sidecars are installable.

    Only a file whose header really is a SQLite WAL / wal-index survives. A
    truncated or mangled sidecar is dropped: SQLite would either refuse to open
    the database over it, or — worse — accept it as a WAL and replay pages that
    were never proven to belong to this database.
    """
    wal = extracted_wal if extracted_wal is not None and is_valid_wal_file(extracted_wal) else None
    shm = (
        extracted_shm
        if extracted_shm is not None and is_valid_wal_index_file(extracted_shm)
        else None
    )
    return _SidecarPlan(wal=wal, shm=shm)


def validate_restore_candidate(
    extracted_db: Path, extracted_wal: Path | None, extracted_shm: Path | None
) -> _SidecarPlan:
    """Validate the database *as it will be restored*, sidecars included.

    The archive's ``-wal`` may hold committed frames the archived main file
    lacks (a checkpoint that stayed busy at pack time), so the pair has to be
    checked together — validating the main file alone would bless a restore
    that comes back stale. The check runs on a throwaway copy because SQLite
    folds the WAL into the main file and *deletes* both sidecars when the last
    connection closes, which would destroy the files we are about to install.

    Returns the plan of sidecars to install. Raises ``ValueError`` if the
    database (with its WAL replayed) does not check out.
    """
    plan = _plan_sidecars(extracted_db, extracted_wal, extracted_shm)
    if not plan.any:
        validate_extracted_db(extracted_db)
        return plan

    with tempfile.TemporaryDirectory() as scratch:
        candidate = Path(scratch) / extracted_db.name
        shutil.copy2(str(extracted_db), str(candidate))
        for sidecar, suffix in ((plan.wal, "-wal"), (plan.shm, "-shm")):
            if sidecar is not None:
                shutil.copy2(str(sidecar), str(Path(f"{candidate}{suffix}")))
        validate_extracted_db(candidate)
    return plan


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
    extracted_wal: Path | None = None,
    extracted_shm: Path | None = None,
) -> list[str]:
    """Atomically restore database and (optionally) media files.

    1. Validate extracted DB (header, integrity, tables).
    2. Checkpoint live WAL.
    3. Back up live DB to ``<live_db>.pre-restore.bak``.
    4. Drop the live DB's stale ``-wal``/``-shm`` sidecars (they would
       otherwise replay pre-restore pages onto the restored main file).
    5. Swap DB atomically (tmp + os.replace).
    6. Install the archive's own ``-wal``/``-shm`` when supplied *and* valid,
       so SQLite replays frames the archived main file was missing.
    7. If *extracted_media* exists, swap media atomically.
    8. On media failure after DB success, roll DB back too.
    9. Clean up backup files on success.

    *session* (when the caller is a request holding one) lets the checkpoint
    reuse that connection instead of opening a second pooled one (deadlock on
    SQLite's size-1 pool).
    """
    from app.core.database import init_db, reinit_engine

    restored: list[str] = []

    # ── Validate ──────────────────────────────────────────────────────────
    sidecars = validate_restore_candidate(extracted_db, extracted_wal, extracted_shm)

    # ── Checkpoint live WAL ───────────────────────────────────────────────
    if live_db.exists():
        await _checkpoint_live(live_db, session)

    # ── Backup live DB ────────────────────────────────────────────────────
    db_backup = live_db.with_suffix(live_db.suffix + ".pre-restore.bak")
    if live_db.exists():
        shutil.copy2(str(live_db), str(db_backup))

    live_wal = Path(f"{live_db}-wal")
    live_shm = Path(f"{live_db}-shm")

    def _clear_sidecars() -> None:
        """Drop the live sidecars so nothing stale is replayed onto *live_db*."""
        live_wal.unlink(missing_ok=True)
        live_shm.unlink(missing_ok=True)

    # ── Swap DB ───────────────────────────────────────────────────────────
    await reinit_engine()  # release file handles
    db_swapped = False
    try:
        # A stale sidecar would resurrect pre-restore pages onto the new main
        # file — the exact data loss a restore is meant to undo.
        _clear_sidecars()
        _atomic_write(extracted_db, live_db)
        # The archive's own WAL is installed so SQLite replays the frames the
        # archived main file was missing (validated above, with those frames).
        for source, destination in sidecars.destinations(live_db):
            _atomic_write(source, destination)
        await init_db()
        restored.append("database")
        db_swapped = True
    except BaseException:
        logger.error("Database restore failed, rolling back", exc_info=True)
        if db_backup.exists():
            _clear_sidecars()  # the pre-restore backup is a bare main file
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
            logger.error("Media restore failed, rolling back database too", exc_info=True)
            if db_swapped and db_backup.exists():
                await reinit_engine()
                _clear_sidecars()
                _atomic_write(db_backup, live_db)
                await init_db()
            db_backup.unlink(missing_ok=True)
            raise

    # ── Success — clean up backup ─────────────────────────────────────────
    db_backup.unlink(missing_ok=True)
    return restored
