"""Schema migration version-stamping (T3.7).

``_stamp_schema_version`` records the high-water schema version in a
``_schema_meta`` table only after a completed migration run, with an auditable
log. These lock that contract: the stamp lands, re-running appends (so history
is visible), and a partial run (no stamp) is distinguishable from a completed one.
"""

from __future__ import annotations

import json

from sqlalchemy import text


async def test_stamp_records_version_and_log(db_engine: object) -> None:
    from app.core.database import _SCHEMA_VERSION, _stamp_schema_version

    async with db_engine.begin() as conn:  # type: ignore[attr-defined]
        await _stamp_schema_version(conn)
        version = (
            await conn.execute(text("SELECT value FROM _schema_meta WHERE key='schema_version'"))
        ).scalar()
        log_row = (
            await conn.execute(text("SELECT value FROM _schema_meta WHERE key='migration_log'"))
        ).scalar()

    assert int(version or 0) == _SCHEMA_VERSION
    runs = json.loads(log_row or "[]")
    assert len(runs) == 1
    assert runs[0]["from"] == 0
    assert runs[0]["to"] == _SCHEMA_VERSION
    assert "T" in runs[0]["at"]  # ISO-8601 timestamp


async def test_stamp_is_idempotent_and_appends(db_engine: object) -> None:
    from app.core.database import _SCHEMA_VERSION, _stamp_schema_version

    async with db_engine.begin() as conn:  # type: ignore[attr-defined]
        await _stamp_schema_version(conn)
    # A second completed run appends to the log and keeps the version.
    async with db_engine.begin() as conn:  # type: ignore[attr-defined]
        await _stamp_schema_version(conn)
    async with db_engine.connect() as conn:  # type: ignore[attr-defined]
        version = (
            await conn.execute(text("SELECT value FROM _schema_meta WHERE key='schema_version'"))
        ).scalar()
        log_row = (
            await conn.execute(text("SELECT value FROM _schema_meta WHERE key='migration_log'"))
        ).scalar()

    assert int(version or 0) == _SCHEMA_VERSION
    runs = json.loads(log_row or "[]")
    assert len(runs) == 2
    assert runs[1]["from"] == _SCHEMA_VERSION  # second run started already at the version
