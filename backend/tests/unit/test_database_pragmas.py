"""SQLite PRAGMA tuning — applied to every connection via the connect listener."""

from __future__ import annotations

import sqlite3


class _RecordingCursor:
    def __init__(self, conn: _RecordingConn) -> None:
        self._conn = conn

    def execute(self, sql: str) -> None:
        self._conn.executed.append(sql)

    def close(self) -> None:
        pass


class _RecordingConn:
    """Fake DBAPI connection that records every executed PRAGMA string."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)


def test_set_sqlite_pragma_applies_all(tmp_path) -> None:
    from app.core.database import _set_sqlite_pragma

    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    try:
        _set_sqlite_pragma(conn, None)

        def pragma(name: str):
            return conn.execute(f"PRAGMA {name}").fetchone()[0]

        assert str(pragma("journal_mode")).lower() == "wal"
        assert pragma("synchronous") == 1  # NORMAL
        assert pragma("foreign_keys") == 1
        assert pragma("busy_timeout") == 5000
        assert pragma("cache_size") == -4000  # ~4 MiB (tuned down from ~20 MiB)
        assert pragma("temp_store") == 2  # MEMORY
    finally:
        conn.close()


def test_wal_autocheckpoint_is_explicitly_set() -> None:
    """WAL is auto-checkpointed every 1000 pages so the -wal file stays bounded.

    SQLite's *default* wal_autocheckpoint is also 1000, so a read-back value can't
    prove we set it — assert the PRAGMA string is emitted instead.
    """
    from app.core.database import _set_sqlite_pragma

    conn = _RecordingConn()
    _set_sqlite_pragma(conn, None)
    assert "PRAGMA wal_autocheckpoint=1000" in conn.executed


def test_pragma_enables_incremental_vacuum_on_new_db(tmp_path) -> None:
    """A fresh DB created under the connect listener gets auto_vacuum=INCREMENTAL."""
    from app.core.database import _set_sqlite_pragma

    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    try:
        _set_sqlite_pragma(conn, None)  # sets auto_vacuum before any table exists
        conn.execute("CREATE TABLE t (x INTEGER)")
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
    finally:
        conn.close()


def test_vacuum_sync_converts_legacy_db(tmp_path) -> None:
    """A legacy DB (auto_vacuum=NONE) is converted in place, data is preserved,
    and a second run is a no-op."""
    from app.core.database import _vacuum_sync

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1), (2), (3)")
        conn.commit()
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0  # NONE
    finally:
        conn.close()

    url = f"sqlite:///{db}"
    assert _vacuum_sync(url) is True  # one-time reformat

    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3  # data preserved
    finally:
        conn.close()

    assert _vacuum_sync(url) is False  # idempotent — no second VACUUM
