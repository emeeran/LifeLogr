"""Foreign-key index coverage.

SQLite does not index foreign keys automatically, so every FK used for
per-parent lookups or cascade deletes needs an explicit index. These lock the
contract that the models declare them (fresh DBs) *and* that
``_INDEX_MIGRATIONS`` creates them on legacy DBs at boot.
"""

from __future__ import annotations

from sqlalchemy import text

# (index name, table) pairs required by the audit fix.
_EXPECTED = [
    ("ix_media_entry_id", "media"),
    ("ix_voice_recordings_entry_id", "voice_recordings"),
    ("ix_voice_recordings_media_id", "voice_recordings"),
    ("ix_video_notes_entry_id", "video_notes"),
    ("ix_note_media_note_id", "note_media"),
    ("ix_note_pages_note_order", "note_pages"),
    ("ix_entry_prompts_entry_id", "entry_prompts"),
    ("ix_sync_queue_is_synced", "sync_queue"),
    ("ix_backup_snapshots_config_id", "backup_snapshots"),
]


async def _index_map(conn) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
    )
    return {name: tbl for name, tbl in rows.fetchall()}


async def test_fresh_db_declares_fk_indexes(db_engine):
    """``create_all`` (the fresh-DB path) builds every model-declared index."""
    async with db_engine.begin() as conn:
        indexes = await _index_map(conn)
    for name, table in _EXPECTED:
        assert indexes.get(name) == table, f"{name} missing on a fresh DB"


async def test_legacy_db_gets_fk_indexes_from_migrations(db_engine):
    """A DB created before the indexes existed is healed by ``_migrate_schema``."""
    from app.core.database import Base

    async with db_engine.begin() as conn:
        # Simulate a legacy DB: drop every index the migrations claim to add.
        for name, _table in _EXPECTED:
            await conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        indexes = await _index_map(conn)
        for name, _table in _EXPECTED:
            assert name not in indexes

        await conn.run_sync(Base.metadata.create_all)
        from app.core.database import _migrate_schema

        await _migrate_schema(conn)
        indexes = await _index_map(conn)

    for name, table in _EXPECTED:
        assert indexes.get(name) == table, f"{name} not created by _migrate_schema"


async def test_index_migrations_cover_the_declared_indexes():
    """Every model-declared FK index also has a legacy-DB migration entry."""
    from app.core.database import Base, _INDEX_MIGRATIONS
    import app.models  # noqa: F401  (registers every model in Base.metadata)

    declared: set[str] = set()
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            declared.add(index.name)
    migration_names = {name for name, _sql in _INDEX_MIGRATIONS}
    missing = declared - migration_names
    assert not missing, f"model indexes missing from _INDEX_MIGRATIONS: {sorted(missing)}"
