"""Runtime relocation of the on-disk data directory (hot-move).

Moves the SQLite database, media, and ancillary files to a new directory and
swaps the live engine to point at it — without a restart. Modeled on
``app.core.restore.atomic_restore``: validate the target, copy everything,
validate the staged DB, then commit (persist the override + mutate the
settings singleton + reinit the engine). Full rollback on any failure; the
old directory is never auto-deleted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings, write_storage_override
from app.core.database import init_db, reinit_engine
from app.core.restore import _checkpoint_live, validate_extracted_db

logger = logging.getLogger(__name__)

# Files that must travel with the data directory.
_PASSENGER_FILES = (".backup-schedule.json", ".runtime-settings.json", ".secret_key")
# Require this multiple of the live data size as free space on the target.
_MIN_HEADROOM_MULT = 1.5


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy *src* to *dst* atomically via a .tmp file + os.replace."""
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copy2(str(src), str(tmp))
        os.replace(str(tmp), str(dst))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _iter_files(root: Path):
    """Yield every regular file under *root* (recursive)."""
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                yield p
    elif root.is_file():
        yield root


def _current_data_size() -> int:
    """Total bytes of the live DB (+wal/shm) and media directory."""
    total = 0
    db = settings.db_path
    for p in (
        db,
        db.with_suffix(db.suffix + "-wal"),
        db.with_suffix(db.suffix + "-shm"),
    ):
        if p.exists():
            total += p.stat().st_size
    media = Path(settings.MEDIA_DIR)
    total += sum(f.stat().st_size for f in _iter_files(media))
    return total


def _validate_target(target: Path, needed_bytes: int) -> Path:
    """Validate a relocation target. Returns the resolved absolute path.

    Raises ``ValueError`` with a user-facing message on any problem.
    """
    from app.core.config import _config_dir

    resolved = target.expanduser().resolve()
    if not resolved.is_absolute():
        raise ValueError("Target path must be absolute.")

    current = Path(settings.DATA_DIR).resolve()
    if resolved == current:
        raise ValueError("That is already the active data directory.")

    # Refuse the config dir (where the override lives) — moving data there
    # would create a self-reference.
    try:
        cfg = _config_dir().resolve()
        if resolved == cfg or cfg in resolved.parents:
            raise ValueError("Cannot relocate into the configuration directory.")
    except OSError:
        pass

    # Parent must exist & be writable.
    parent = resolved.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not os.access(str(parent), os.W_OK):
        raise ValueError(f"Parent directory is not writable: {parent}")

    # Free-space headroom.
    usage = shutil.disk_usage(str(parent))
    required = int(needed_bytes * _MIN_HEADROOM_MULT)
    if usage.free < required:
        raise ValueError(
            f"Not enough free space on {parent}: need ~{required} bytes, have {usage.free}."
        )

    # Don't clobber an existing non-empty directory.
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"Target directory is not empty: {resolved}")

    return resolved


def _cleanup(paths: list[Path]) -> None:
    """Best-effort removal of staged files/dirs (rollback helper)."""
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            logger.warning("Could not clean up %s during rollback", p, exc_info=True)


async def relocate_storage(
    target_data_dir: str | Path,
    session: AsyncSession | None = None,
) -> dict[str, object]:
    """Hot-move DATA_DIR to *target_data_dir* and swap the live engine.

    Returns ``{"old_path", "new_path", "copied_bytes"}``. On failure the live
    app is left untouched (settings + engine restored, old dir intact).
    """
    # The size walk stats() every file under MEDIA_DIR — off the event loop so a
    # large media tree can't stall serving during a storage relocate.
    target = _validate_target(
        Path(target_data_dir), await asyncio.to_thread(_current_data_size)
    )

    old_dir = Path(settings.DATA_DIR)
    old_db = settings.db_path
    db_name = old_db.name

    # 1. Flush WAL into the main DB file before copying. Pass the caller's
    #    session to avoid the size-1 pool deadlock (see atomic_restore).
    await _checkpoint_live(old_db, session)

    target.mkdir(parents=True, exist_ok=True)

    # 2. Stage every passenger into the target.
    staged: list[Path] = []
    try:
        for p in (
            old_db,
            old_db.with_suffix(old_db.suffix + "-wal"),
            old_db.with_suffix(old_db.suffix + "-shm"),
        ):
            if p.exists():
                _atomic_copy(p, target / p.name)
                staged.append(target / p.name)

        old_media = Path(settings.MEDIA_DIR)
        if old_media.is_dir() and any(old_media.iterdir()):
            shutil.copytree(old_media, target / "media")
            staged.append(target / "media")

        for name in _PASSENGER_FILES:
            src = old_dir / name
            if src.exists():
                _atomic_copy(src, target / name)
                staged.append(target / name)
    except BaseException:
        logger.error("Relocate failed during copy; cleaning target", exc_info=True)
        _cleanup(staged)
        if target.exists() and not any(target.iterdir()):
            target.rmdir(missing_ok=True)
        raise

    # 3. Validate the staged DB before committing.
    staged_db = target / db_name
    if staged_db.exists():
        try:
            validate_extracted_db(staged_db)
        except ValueError:
            logger.error("Staged database failed validation; aborting relocate")
            _cleanup(staged)
            raise

    copied_bytes = sum(f.stat().st_size for f in _iter_files(target))

    # 4. Commit point: persist intent, then mutate singleton + swap engine.
    write_storage_override(target)
    try:
        settings.DATA_DIR = target
        settings.MEDIA_DIR = target / "media"
        settings.DATABASE_URL = f"sqlite+aiosqlite:///{target / db_name}"
        settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        await reinit_engine()
        await init_db()
    except BaseException:
        logger.error(
            "Relocate failed during engine swap; rolling back override + settings",
            exc_info=True,
        )
        write_storage_override(old_dir)
        settings.DATA_DIR = old_dir
        settings.MEDIA_DIR = old_dir / "media"
        settings.DATABASE_URL = f"sqlite+aiosqlite:///{old_db}"
        try:
            await reinit_engine()  # release the target; engine now on old path
            _cleanup(staged)  # remove orphaned copies
            await init_db()
        except Exception:
            logger.critical(
                "Rollback engine swap failed — app may be in a bad state",
                exc_info=True,
            )
        raise

    logger.info("Relocated data dir %s -> %s", old_dir, target)
    return {
        "old_path": str(old_dir),
        "new_path": str(target),
        "copied_bytes": copied_bytes,
    }
