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


def _plant_snapshot(data_dir: Path, ts: str, *, junk: bytes = b"snapshot") -> Path:
    """Plant a snapshot file with the given embedded timestamp (rotation only
    walks names, so the bytes don't matter here)."""
    snap = data_dir / f"{_BOOT_SNAPSHOT_PREFIX}{ts}"
    snap.write_bytes(junk)
    return snap


def test_snapshot_rotation_keeps_recent_plus_weekly(tmp_path: Path) -> None:
    """Rotation keeps the 2 newest snapshots plus the newest of each earlier
    ISO week (LW-4.2) — not a flat newest-N."""
    from app.core.database import _rotate_boot_snapshots

    # 2026-01-05 (Mon) .. 2026-01-10 (Sat) are all ISO week 2026-W02; Jan 20-21
    # are week W04.
    for i, day in enumerate(range(5, 11)):  # 2026-01-05 .. 2026-01-10 (all W02)
        _plant_snapshot(tmp_path, f"202601{day:02d}-00000{i}")
    _plant_snapshot(tmp_path, "20260120-000000")
    _plant_snapshot(tmp_path, "20260121-000000")

    _rotate_boot_snapshots(tmp_path, keep_recent=2)

    snaps = sorted(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))
    assert [s.name[len(_BOOT_SNAPSHOT_PREFIX) :] for s in snaps] == [
        "20260110-000005",  # newest snapshot of the earlier week (W02)
        "20260120-000000",  # 2 most recent full copies
        "20260121-000000",
    ]


def test_rotation_ignores_snapshot_sidecars(tmp_path: Path) -> None:
    """``-wal``/``-shm`` files sitting beside a snapshot (left by an older
    read-only connection) must not be counted as snapshots by rotation or
    recovery — they can never be a restorable DB."""
    from app.core.database import _boot_snapshots, _rotate_boot_snapshots

    _plant_snapshot(tmp_path, "20260101-000000")
    _plant_snapshot(tmp_path, "20260102-000000")
    (tmp_path / f"{_BOOT_SNAPSHOT_PREFIX}20260101-000000-shm").write_bytes(b"shm")
    (tmp_path / f"{_BOOT_SNAPSHOT_PREFIX}20260101-000000-wal").write_bytes(b"wal")

    names = [p.name for p in _boot_snapshots(tmp_path)]
    assert len(names) == 2  # sidecars filtered out

    _rotate_boot_snapshots(tmp_path, keep_recent=2)
    # Nothing pruned: the two real snapshots are the recent tier; the sidecars
    # are left alone (SQLite owns them).
    assert len(list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))) == 4


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
    # A second (newer) snapshot that is itself corrupt — planted directly,
    # since _create_boot_snapshot_sync now skips unchanged-DB copies.
    bad = _plant_snapshot(tmp_path, "20260102-000000", junk=db.read_bytes())
    _corrupt(bad)
    assert good is not None

    _corrupt(db)
    _preflight_db_file_sync(db, tmp_path)

    assert _integrity_check_sync(db) == "ok"
    assert _row_bodies(db) == ["hello"]  # restored from the good snapshot


def test_preflight_skips_missing_db(tmp_path: Path) -> None:
    # Fresh boot with no DB file: nothing to do, no error.
    _preflight_db_file_sync(tmp_path / "lifelogr.db", tmp_path)
    assert not list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))


# ── LW-4: quick_check boot path + snapshot skip/rotation ─────────────────────


def test_snapshot_taken_even_when_shape_unchanged(tmp_path: Path) -> None:
    """A same-size, same-page-count edit still produces a fresh snapshot.

    The old (size, page_count) fingerprint skip was removed: an in-place
    same-length UPDATE (edited body, is_deleted flip) changes neither value,
    so the "unchanged" snapshot could silently be weeks old when corruption
    recovery needs it (audit blocker, 2026-11-20)."""
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)

    first = _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    assert first is not None

    # In-place same-length rewrite: neither size nor page_count moves.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("UPDATE t SET body = 'howdy' WHERE id = 1")
        conn.commit()
    finally:
        conn.close()

    second = _create_boot_snapshot_sync(db, tmp_path, _ts="20260102-000000")
    assert second is not None
    snaps = sorted(s.name for s in tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))
    assert snaps == sorted([first.name, second.name])


def test_snapshot_taken_when_db_changed(tmp_path: Path) -> None:
    """A DB whose page count changed since the newest snapshot is re-copied."""
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    first = _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    assert first is not None

    # A new table allocates at least one page → page_count differs.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE u (x INTEGER)")
        conn.execute("INSERT INTO u VALUES (1)")
        conn.commit()
    finally:
        conn.close()

    second = _create_boot_snapshot_sync(db, tmp_path, _ts="20260102-000000")
    assert second is not None and second.exists()
    assert second.name != first.name


def test_preflight_healthy_db_skips_full_integrity_check(tmp_path: Path, monkeypatch) -> None:
    """Boot with a healthy DB runs quick_check only — the full integrity_check
    must not run on this path (LW-4.1)."""
    import app.core.database as dbmod

    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)

    calls = {"full": 0}

    def _spy(path):
        calls["full"] += 1
        return "ok"

    monkeypatch.setattr(dbmod, "_integrity_check_sync", _spy)
    _preflight_db_file_sync(db, tmp_path)

    assert calls["full"] == 0  # healthy quick_check → no escalation
    snaps = list(tmp_path.glob(f"{_BOOT_SNAPSHOT_PREFIX}*"))
    assert len(snaps) == 1
    assert _integrity_check_sync(snaps[0]) == "ok"


def test_preflight_corrupt_db_still_recovers(tmp_path: Path) -> None:
    """A corrupt file still fails boot (quick_check → full check → recovery).

    Regression guard for the quick_check swap: the recovery path must behave
    exactly as it did under the full-check-only boot.
    """
    db = tmp_path / "lifelogr.db"
    _make_valid_db(db)
    _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
    _corrupt(db)

    # quick_check sees the corruption too (it scans b-tree pages).
    from app.core.database import _quick_check_sync

    assert _quick_check_sync(db) != "ok"

    _preflight_db_file_sync(db, tmp_path)
    assert _integrity_check_sync(db) == "ok"
    assert _row_bodies(db) == ["hello"]
    assert list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))


# ── LW-4.1: the weekly full-integrity-check job ──────────────────────────────


class TestWeeklyIntegrityJob:
    """``_run_full_integrity_check`` — the exhaustive scan moved out of boot."""

    async def test_healthy_db_is_left_alone(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import AsyncMock

        import app.core.database as dbmod
        from app.core.config import settings

        db = tmp_path / "lifelogr.db"
        _make_valid_db(db)
        saved = (settings.DATABASE_URL, settings.DATA_DIR)
        settings.DATABASE_URL = f"sqlite+aiosqlite:///{db}"
        settings.DATA_DIR = tmp_path
        mock_reinit = AsyncMock()
        monkeypatch.setattr(dbmod, "reinit_engine", mock_reinit)
        try:
            from app.services.scheduler_service import _run_full_integrity_check

            await _run_full_integrity_check()
        finally:
            settings.DATABASE_URL, settings.DATA_DIR = saved

        mock_reinit.assert_not_awaited()
        assert _integrity_check_sync(db) == "ok"
        assert not list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))

    async def test_corrupt_db_recovers_and_reinits_engine(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import AsyncMock

        import app.core.database as dbmod
        from app.core.config import settings

        db = tmp_path / "lifelogr.db"
        _make_valid_db(db)
        # A prior boot left a good snapshot.
        _create_boot_snapshot_sync(db, tmp_path, _ts="20260101-000000")
        _corrupt(db)

        saved = (settings.DATABASE_URL, settings.DATA_DIR)
        settings.DATABASE_URL = f"sqlite+aiosqlite:///{db}"
        settings.DATA_DIR = tmp_path
        mock_reinit = AsyncMock()
        monkeypatch.setattr(dbmod, "reinit_engine", mock_reinit)
        try:
            from app.core.startup_checks import _app_integrity_result

            _app_integrity_result.clear()
            from app.services.scheduler_service import _run_full_integrity_check

            await _run_full_integrity_check()  # must not raise
        finally:
            settings.DATABASE_URL, settings.DATA_DIR = saved

        # Live repair was removed (it raced in-flight writers): the corrupt file
        # is NOT touched, no engine swap, and the alert lands in the report.
        assert _integrity_check_sync(db) != "ok"  # still corrupt
        assert not list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))
        mock_reinit.assert_not_awaited()
        from app.core.startup_checks import get_app_integrity, get_integrity_status

        report = get_app_integrity()
        assert any(c["id"] == "db-corrupt-runtime" for c in report["checks"])
        assert get_integrity_status()["ok"] is False

    async def test_never_raises_when_recovery_impossible(self, tmp_path, monkeypatch) -> None:
        from app.core.config import settings

        db = tmp_path / "lifelogr.db"
        _make_valid_db(db)
        _corrupt(db)  # no snapshot exists → boot recovery won't help either

        saved = (settings.DATABASE_URL, settings.DATA_DIR)
        settings.DATABASE_URL = f"sqlite+aiosqlite:///{db}"
        settings.DATA_DIR = tmp_path
        try:
            from app.services.scheduler_service import _run_full_integrity_check

            await _run_full_integrity_check()  # logs, does not raise
        finally:
            settings.DATABASE_URL, settings.DATA_DIR = saved
        # Alert-only: nothing quarantined at runtime (boot preflight owns that).
        assert not list(tmp_path.glob(f"{_CORRUPT_PREFIX}*"))

    async def test_registered_through_scheduler_service(self) -> None:
        """The job goes through SchedulerService conventions (id, cron,
        coalesce, single-instance) — never a bare scheduler (LW-4.1)."""
        from app.services.scheduler_service import SchedulerService

        sched = SchedulerService.get_scheduler()
        if not sched.running:
            sched.start()
        try:
            assert await SchedulerService.register_weekly_integrity_check() == 1
            job = sched.get_job("full_integrity_check")
            assert job is not None
            assert job.id == "full_integrity_check"
            assert job.max_instances == 1
            assert job.coalesce  # type: ignore[comparison-overlap]
        finally:
            if sched.get_job("full_integrity_check"):
                sched.remove_job("full_integrity_check")
            if sched.running:
                sched.shutdown(wait=False)

    async def test_register_is_noop_when_scheduler_stopped(self) -> None:
        from app.services.scheduler_service import SchedulerService

        sched = SchedulerService.get_scheduler()
        if sched.running:
            sched.shutdown(wait=False)
        assert await SchedulerService.register_weekly_integrity_check() == 0
        assert sched.get_job("full_integrity_check") is None


# ── init_db hook (desktop sidecar) ────────────────────────────────────────────


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
