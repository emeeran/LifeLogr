"""Tests for the startup foundation fixes: SECRET_KEY loader, DB migration of
passenger files, and the SQLite connection-pool config.

These mirror the config-override tests in test_storage_service.py: they call the
module-level helpers directly with isolated temp dirs + monkeypatched env so the
real data dir / key file is never touched.
"""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

from app.core.config import _migrate_existing_db, _resolve_secret_key

_DEFAULT = "change-me-before-production"


# ── _resolve_secret_key ──────────────────────────────────────────────────────


def test_resolve_secret_key_explicit_non_default_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / ".secret_key").write_text("filekey" * 8)
    # An explicitly-provided non-default key is always honoured.
    assert _resolve_secret_key(tmp_path, "my-explicit-key") == "my-explicit-key"


def test_resolve_secret_key_no_data_dir_env_is_noop(tmp_path: Path, monkeypatch) -> None:
    # Dev / server (no DATA_DIR env) keeps the default — behaviour unchanged.
    monkeypatch.delenv("DATA_DIR", raising=False)
    (tmp_path / ".secret_key").write_text("filekey" * 8)
    assert _resolve_secret_key(tmp_path, _DEFAULT) == _DEFAULT
    assert not (tmp_path / ".secret_key").exists() or (tmp_path / ".secret_key").read_text() == "filekey" * 8


def test_resolve_secret_key_loads_existing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    expected = "deadbeef" * 8
    (tmp_path / ".secret_key").write_text(expected)
    assert _resolve_secret_key(tmp_path, _DEFAULT) == expected


def test_resolve_secret_key_generates_and_persists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    key = _resolve_secret_key(tmp_path, _DEFAULT)
    assert key and key != _DEFAULT
    kf = tmp_path / ".secret_key"
    assert kf.exists()
    assert kf.read_text() == key  # persisted for next run
    assert stat.S_IMODE(kf.stat().st_mode) == 0o600  # locked down


def test_resolve_secret_key_generated_key_is_hex(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    key = _resolve_secret_key(tmp_path, _DEFAULT)
    # secrets.token_hex(32) → 64 hex chars.
    assert len(key) == 64
    int(key, 16)  # raises if not hex


# ── _migrate_existing_db carries passenger files ─────────────────────────────


def test_migrate_copies_secret_key_and_passengers(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "lifelogr.db").write_bytes(b"x" * 32)  # non-empty → eligible
    (legacy / ".secret_key").write_text("migratedkey" * 4)
    (legacy / ".runtime-settings.json").write_text("{}")
    monkeypatch.setattr("app.core.config._default_data_dir", lambda: legacy)

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target_db = target_dir / "lifelogr.db"

    _migrate_existing_db(target_db, target_dir)

    assert target_db.exists()
    assert (target_dir / ".secret_key").read_text() == "migratedkey" * 4
    assert (target_dir / ".runtime-settings.json").read_text() == "{}"


def test_migrate_skips_when_target_db_present(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "lifelogr.db").write_bytes(b"x" * 32)
    (legacy / ".secret_key").write_text("legacy" * 8)
    monkeypatch.setattr("app.core.config._default_data_dir", lambda: legacy)

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target_db = target_dir / "lifelogr.db"
    target_db.write_bytes(b"already-here")  # present → no migration

    _migrate_existing_db(target_db, target_dir)
    assert target_db.read_bytes() == b"already-here"
    assert not (target_dir / ".secret_key").exists()  # nothing copied


# ── SQLite engine uses the configured pool size (not hardcoded 1) ────────────


def test_sqlite_engine_uses_configured_pool_size(tmp_path: Path, monkeypatch) -> None:
    from app.core import database as dbmod
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    eng, _factory = dbmod._build_engine()
    try:
        # SQLite no longer forces pool_size=1; it honours settings (default 5).
        assert eng.pool.size() == settings.DB_POOL_SIZE
        assert settings.DB_POOL_SIZE > 1
    finally:
        eng.sync_engine.dispose()


# ── serializable_write serializes background write jobs ──────────────────────


async def test_serializable_write_serializes_concurrent_callers(monkeypatch) -> None:
    import app.core.database as dbmod

    # Fresh lock bound to this test's loop (the module global can outlive prior loops).
    monkeypatch.setattr(dbmod, "_write_lock", asyncio.Lock())
    order: list[str] = []

    async def task(label: str) -> None:
        async with dbmod.serializable_write():
            order.append(f"{label}-in")
            await asyncio.sleep(0.03)
            order.append(f"{label}-out")

    await asyncio.gather(task("a"), task("b"))
    # Critical sections must not interleave — one fully completes before the other.
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )
