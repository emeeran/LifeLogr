"""Tests for runtime data-directory relocation (config override + storage_service).

These use a bespoke fixture (``isolated_data_env``) rather than the shared
``client`` fixture: relocate swaps the app's *global* engine via
``reinit_engine()``, which is incompatible with the conftest client's separate
test engine. Each test points ``settings`` + the global engine at an isolated
temp DATA_DIR and restores them on teardown without touching the real dev DB.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.core import database as dbmod
from app.core.config import (
    Settings,
    _read_storage_override,
    settings,
    write_storage_override,
)
from app.models.entry import Entry


# ── config override: read/write + Settings precedence (no engine) ────────────


def test_override_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "elsewhere" / "data"
    write_storage_override(target)
    assert _read_storage_override() == target


def test_override_ignores_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # Malformed / relative entries are ignored.
    from app.core.config import _storage_override_path

    p = _storage_override_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"data_dir": "relative/path"}')
    assert _read_storage_override() is None


def test_settings_honors_override_over_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("LIFELOGR_DATA_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    # Set DATABASE_URL so model_post_init skips _migrate_existing_db.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    chosen = tmp_path / "chosen" / "data"
    write_storage_override(chosen)
    s = Settings()
    assert Path(s.DATA_DIR) == chosen


def test_settings_env_beats_override(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    env_dir = tmp_path / "envdir"
    monkeypatch.setenv("LIFELOGR_DATA_DIR", str(env_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'y.db'}")
    write_storage_override(tmp_path / "override" / "data")
    s = Settings()
    assert Path(s.DATA_DIR) == env_dir


# ── relocate (needs the global engine pointed at an isolated DATA_DIR) ───────


@pytest_asyncio.fixture
async def isolated_data_env(tmp_path, monkeypatch):
    """Point settings + global engine at an isolated temp DATA_DIR with schema."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "media").mkdir()
    (data_dir / ".secret_key").write_text("original-secret")

    saved = (settings.DATA_DIR, settings.MEDIA_DIR, settings.DATABASE_URL)
    settings.DATA_DIR = data_dir
    settings.MEDIA_DIR = data_dir / "media"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{data_dir / 'lifelogr.db'}"
    await dbmod.reinit_engine()
    await dbmod.init_db()
    try:
        yield data_dir
    finally:
        settings.DATA_DIR, settings.MEDIA_DIR, settings.DATABASE_URL = saved
        await dbmod.reinit_engine()  # rebuild against original URL (lazy; no writes)


async def _count_entries() -> int:
    async with dbmod.async_session() as s:
        return (await s.execute(select(func.count()).select_from(Entry))).scalar() or 0


@pytest.mark.asyncio
async def test_relocate_success(isolated_data_env, tmp_path):
    from app.services.storage_service import relocate_storage

    async with dbmod.async_session() as s:
        s.add(Entry(entry_date=date(2024, 1, 1), body="hello world", title="t"))
        await s.commit()
    assert await _count_entries() == 1

    new_dir = tmp_path / "newdata"
    result = await relocate_storage(new_dir)

    assert Path(result["old_path"]) == isolated_data_env
    assert Path(result["new_path"]) == new_dir.resolve()
    # settings mutated + override persisted
    assert Path(settings.DATA_DIR) == new_dir.resolve()
    assert _read_storage_override() == new_dir.resolve()
    # secret carried to the new location; old dir left intact
    assert (new_dir / ".secret_key").read_text() == "original-secret"
    assert (isolated_data_env / ".secret_key").exists()
    assert (isolated_data_env / "lifelogr.db").exists()
    # entry survived on the new DB (global engine now points at new_dir)
    assert await _count_entries() == 1
    # FTS index rebuilt against the new DB
    async with dbmod.async_session() as s:
        fts = (await s.execute(text("SELECT count(*) FROM entries_fts"))).scalar()
    assert fts == 1


@pytest.mark.asyncio
async def test_relocate_rejects_same_dir(isolated_data_env):
    from app.services.storage_service import relocate_storage

    with pytest.raises(ValueError, match="already the active"):
        await relocate_storage(isolated_data_env)


@pytest.mark.asyncio
async def test_relocate_rejects_nonempty_target(isolated_data_env, tmp_path):
    from app.services.storage_service import relocate_storage

    target = tmp_path / "nonempty"
    target.mkdir()
    (target / "junk").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        await relocate_storage(target)


@pytest.mark.asyncio
async def test_relocate_rejects_config_dir(isolated_data_env, tmp_path):
    from app.core.config import _config_dir
    from app.services.storage_service import relocate_storage

    with pytest.raises(ValueError, match="configuration directory"):
        await relocate_storage(_config_dir())


@pytest.mark.asyncio
async def test_relocate_rollback_on_engine_failure(isolated_data_env, tmp_path, monkeypatch):
    from app.services import storage_service as ss

    async with dbmod.async_session() as s:
        s.add(Entry(entry_date=date(2024, 1, 1), body="keep me"))
        await s.commit()

    new_dir = tmp_path / "newdata2"

    async def boom(*_a, **_kw):
        raise RuntimeError("induced")

    monkeypatch.setattr(ss, "init_db", boom)

    with pytest.raises(RuntimeError, match="induced"):
        await ss.relocate_storage(new_dir)

    # settings + override restored to the old path
    assert Path(settings.DATA_DIR) == isolated_data_env
    assert _read_storage_override() == isolated_data_env
    # old DB intact + readable
    assert await _count_entries() == 1
    # staged files cleaned up
    assert not (new_dir / "lifelogr.db").exists()
