"""SQLite PRAGMA tuning — applied to every connection via the connect listener."""

import sqlite3


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
        assert pragma("cache_size") == -20000
        assert pragma("temp_store") == 2  # MEMORY
    finally:
        conn.close()
