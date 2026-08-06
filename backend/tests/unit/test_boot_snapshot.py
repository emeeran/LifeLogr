"""Boot-time DB safety snapshot + integrity auto-recovery.

Covers the file-level preflight in ``app.core.database``: a rotating snapshot of
``lifelogr.db`` taken before migrations run, and automatic restore from the
newest good snapshot when ``PRAGMA integrity_check`` fails at boot — the
self-healing layer behind the "database must be protected / verify integrity on
load" requirement.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.database import (
    _BOOT_SNAPSHOT_PREFIX,
    _CORRUPT_PREFIX,
    _create_boot_snapshot_sync,
    _integrity_check_sync,
    _preflight_db_file_sync,
)


def _make_valid_db(db_path: Path, *, row: tuple[int, str] = (1, "hello")) -> None:
    """Create a small valid SQLite DB with one row in a `t` table."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO t (id, body) VALUES (?, ?)", row)
        conn.commit()
    finally:
        conn.close()


def _row_bodies(db_path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute("SELECT body FROM t ORDER BY id")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _corrupt(db_path: Path) -> None:
    """Truncate the DB file so PRAGMA integrity_check fails."""
    raw = db_path.read_bytes()
    db_path.write_bytes(raw[: len(raw) // 2])


# ── snapshot creation + rotation ──────────────────────────────────────────────


def test_snapshot_created_for_valid_db(tmp_path: Path) -> None:
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)

    snap = _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")

    assert snap is not None and snap.exists()
    assert snap.name == f"{_BOOT_SNAPSHOT_PREFIX}20260101-000000"
    # Snapshot is itself intact and holds the same data.
    assert _integrity_check_sync(snap) == "ok"
    assert _row_bodies(snap) == ["hello"]


def test_snapshot_skips_missing_or_empty_db(tmp_path: Path) -> None:
    missing = tmp_path / "lifelogr.db"
    assert _create_boot_snapshot_sync(missing, tmp_path) is None
    assert not list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))

    empty = tmp_path / "lifelogr.db"
    empty.write_bytes(b"")
    assert _create_boot_snapshot_sync(empty, tmp_path) is None


def test_snapshot_rotation_keeps_newest(tmp_path: Path) -> None:
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    retention = 3
    for i in range(6):
        _create_boot_snapshot_sync(db, tmp_path, retention=retention, _ts=f"2026010{i}-000000")
    snaps = sorted(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))
    assert len(snaps) == retention
    # The newest three (05, 04, 03) survived; 00–02 were pruned. Compare by the
    # timestamp suffix embedded in the filename (after the snapshot prefix).
    assert [s.name[len(_BOOT_SNAPSHOT_PREFIX) :] for s in snaps] == [
        "20260103-000000",
        "20260104-000000",
        "20260105-000000",
    ]


# ── corruption → recovery ────────────────────────────────────────────────────


def test_corrupt_db_recovers_from_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    # A prior boot left a good snapshot.
    _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    # Stale WAL sidecars from the (about-to-corrupt) live file.
    (tmp_path / "lifelogr.db-wal").write_bytes(b"WAL")
    (tmp_path / "lifelogr.db-shm").write_bytes(b"SHM")

    assert _integrity_check_sync(db) == "ok"
    _corrupt(db)
    assert _integrity_check_sync(db) != "ok"

    _preflight_db_file_sync(db, tmp_path)

    # Live DB restored from the snapshot: intact, original row present.
    assert _integrity_check_sync(db) == "ok"
    assert _row_bodies(db) == ["hello"]
    # Corrupt file preserved for forensics.
    assert list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))


def test_recovery_clears_stale_wal_sidecars(tmp_path: Path) -> None:
    """Recovery removes the corrupt DB's stale -wal/-shm right after restore.

    Asserted before any connection reopens the restored (WAL-mode) DB, since such
    a reopen legitimately recreates fresh valid sidecars — what matters is that
    the *stale* sidecars belonging to the corrupt file do not survive the swap.
    """
    from app.core.database import _recover_from_snapshot_sync

    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    (tmp_path / "lifelogr.db-wal").write_bytes(b"WAL")
    (tmp_path / "lifelogr.db-shm").write_bytes(b"SHM")
    _corrupt(db)

    assert _recover_from_snapshot_sync(db, tmp_path, _ts="20260801-000000") is True

    # Live sidecars gone immediately after the swap (a later reopen recreates
    # fresh ones; that is expected and not what we assert here).
    assert not (tmp_path / "lifelogr.db-wal").exists()
    assert not (tmp_path / "lifelogr.db-shm").exists()
    assert (tmp_path / f"{_CORRUPT_PREFIX}20260801-000000").exists()
    assert _integrity_check_sync(db) == "ok"


def test_corrupt_db_with_no_snapshot_raises_and_quarantines(tmp_path: Path) -> None:
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    _corrupt(db)

    with pytest.raises(RuntimeError, match="no intact boot snapshot"):
        _preflight_db_file_sync(db, tmp_path)

    # The corrupt file was still preserved (never silently destroyed).
    assert list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))


def test_corrupt_snapshot_is_skipped_during_recovery(tmp_path: Path) -> None:
    """A snapshot that is itself corrupt must not be chosen for restore."""
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    good = _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    # Add a second, corrupt snapshot (newer mtime) — must be skipped, not used.
    bad = _create_boot_snapshot_sync(db, tmp_path, _ts="20260102-000000")
    assert bad is not None and good is not None
    _corrupt(bad)

    _corrupt(db)
    _preflight_db_file_sync(db, tmp_path)

    assert _integrity_check_sync(db) == "ok"
    assert _row_bodies(db) == ["hello"]  # restored from the good snapshot


def test_preflight_skips_missing_db(tmp_path: Path) -> None:
    # Fresh boot with no DB file: nothing to do, no error.
    _preflight_db_file_sync(tmp_path / "lifelogr.db", tmp_path)
    assert not list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))


# ── init_db hook (desktop sidecar) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_db_snapshots_existing_db_on_desktop(tmp_path: Path, monkeypatch) -> None:
    """init_db must snapshot an existing DB on the desktop sidecar (DATA_DIR set)."""
    import app.core.database as dbmod
    from app.core.config import settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # is_desktop_sidecar = True
    db_path = tmp_path / "lifelogr.db"
    saved = (settings.DATA_DIR, settings.MEDIA_DIR, settings.DATABASE_URL)
    settings.DATA_DIR = tmp_path
    settings.MEDIA_DIR = tmp_path / "media"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
    try:
        await dbmod.reinit_engine()
        await dbmod.init_db()  # first boot: DB created, preflight had nothing to snapshot
        assert db_path.exists()
        assert not list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))

        await dbmod.init_db()  # second boot: DB exists → preflight snapshots it
        snaps = list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))
        assert len(snaps) == 1
        assert _integrity_check_sync(snaps[0]) == "ok"
    finally:
        settings.DATA_DIR, settings.MEDIA_DIR, settings.DATABASE_URL = saved
        await dbmod.reinit_engine()
