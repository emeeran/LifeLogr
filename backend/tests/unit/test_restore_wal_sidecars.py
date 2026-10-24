"""WAL sidecar handling on restore.

Three guarantees, each pinning a way a restore used to lose or resurrect data:

1. The live DB's stale ``-wal``/``-shm`` are removed around the swap — SQLite
   would otherwise replay pre-restore pages onto the restored main file, so the
   "restored" database silently came back as the old one.
2. An archive's own sidecars are installed, so committed frames the archived
   main file was missing (a checkpoint that stayed busy at pack time) are
   replayed instead of lost.
3. A sidecar without a genuine SQLite header is dropped, never installed.
"""

from __future__ import annotations

import io
import sqlite3
import tarfile
from pathlib import Path

import pytest

from app.core.restore import (
    _SidecarPlan,
    atomic_restore,
    validate_restore_candidate,
)

# The SQLite WAL magic, big-endian (the two values distinguish checksum order).
_WAL_MAGICS = (b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83")

_DDL = (
    "CREATE TABLE entries ("
    "id INTEGER PRIMARY KEY, "
    "entry_date DATE NOT NULL, "
    "body TEXT NOT NULL)"
)


@pytest.fixture(autouse=True)
def _no_engine_swap(monkeypatch):
    """Stop atomic_restore from swapping the real app engine around.

    The tests observe file-level effects (which sidecar landed where), and a
    real ``init_db`` would open — and so checkpoint and delete — the very
    sidecar under test.
    """
    import app.core.database as dbmod

    async def _noop() -> None:
        return None

    monkeypatch.setattr(dbmod, "reinit_engine", _noop)
    monkeypatch.setattr(dbmod, "init_db", _noop)


def _make_db(path: Path, body: str = "seed") -> Path:
    """A minimal valid SQLite DB holding one entry."""
    conn = sqlite3.connect(str(path))
    conn.execute(_DDL)
    conn.execute("INSERT INTO entries (entry_date, body) VALUES ('2026-01-01', ?)", (body,))
    conn.commit()
    conn.close()
    return path


def _wal_archive_pair(path: Path, body: str) -> tuple[Path, bytes, bytes]:
    """A DB whose newest commit lives *only* in its ``-wal``.

    Returns the main file, WAL bytes and SHM bytes captured while the
    connection is still open — SQLite checkpoints and deletes the sidecars on
    close, which is precisely the state an archive can catch the live DB in.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL)
    conn.commit()
    conn.execute("INSERT INTO entries (entry_date, body) VALUES ('2026-02-02', ?)", (body,))
    conn.commit()

    wal = Path(f"{path}-wal").read_bytes()
    shm = Path(f"{path}-shm").read_bytes()
    main = Path(path).read_bytes()  # pre-checkpoint: the row is not in here yet
    conn.close()

    assert wal, "expected committed frames to still be in the WAL"
    assert wal[:4] in _WAL_MAGICS, "expected a real SQLite WAL"
    # Re-materialise the main file (the connection's close checkpointed it).
    path.write_bytes(main)
    return path, wal, shm


def _archive(
    tmp_path: Path,
    db: bytes,
    *,
    wal: bytes | None = None,
    shm: bytes | None = None,
    name: str = "diarium.diarium",
) -> Path:
    """A .tar.gz holding a DB (and optionally its sidecars), as archives do."""
    archive = tmp_path / f"{name}-archive.tar.gz"
    with tarfile.open(str(archive), "w:gz") as tar:
        members = [("diarium.diarium", db)]
        if wal is not None:
            members.append(("diarium.diarium-wal", wal))
        if shm is not None:
            members.append(("diarium.diarium-shm", shm))
        for member_name, payload in members:
            info = tarfile.TarInfo(name=member_name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return archive


def _extract(archive: Path, dest: Path) -> None:
    from app.core.archive import extract_archive_file

    dest.mkdir(parents=True, exist_ok=True)
    extract_archive_file(archive, dest)


async def _restore(tmp_path: Path, archive: Path, live: Path) -> list[str]:
    extract_dir = tmp_path / "extracted"
    _extract(archive, extract_dir)
    extracted_db = extract_dir / "diarium.diarium"
    media = extract_dir / "media"
    media.mkdir(exist_ok=True)
    return await atomic_restore(
        extracted_db=extracted_db,
        extracted_media=None,
        live_db=live,
        live_media=media,
        extracted_wal=Path(f"{extracted_db}-wal"),
        extracted_shm=Path(f"{extracted_db}-shm"),
    )


def _bodies(db: Path) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT body FROM entries").fetchall()]
    finally:
        conn.close()


class TestStaleSidecarsRemoved:
    async def test_live_sidecars_are_dropped_on_restore(self, tmp_path: Path) -> None:
        """The old data's sidecars must not survive the swap."""
        live = _make_db(tmp_path / "live.db", body="old")
        Path(f"{live}-wal").write_bytes(b"stale-wal-bytes")
        Path(f"{live}-shm").write_bytes(b"stale-shm-bytes")

        fresh = _make_db(tmp_path / "fresh.db", body="new")
        await _restore(tmp_path, _archive(tmp_path, fresh.read_bytes()), live)

        assert not Path(f"{live}-wal").exists()
        assert not Path(f"{live}-shm").exists()
        assert _bodies(live) == ["new"]

    async def test_sidecars_dropped_on_rollback(self, tmp_path: Path) -> None:
        """A failed swap restores the bare backup file without stale sidecars."""
        live = _make_db(tmp_path / "live.db", body="old")
        Path(f"{live}-wal").write_bytes(b"stale-wal-bytes")

        fresh = _make_db(tmp_path / "fresh.db", body="new")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        fresh_archived = extract_dir / "diarium.diarium"
        fresh_archived.write_bytes(fresh.read_bytes())

        import unittest.mock as mock

        with mock.patch(
            "app.core.restore._atomic_write", side_effect=OSError("disk gone")
        ):
            with pytest.raises(OSError):
                await atomic_restore(
                    extracted_db=fresh_archived,
                    extracted_media=None,
                    live_db=live,
                    live_media=tmp_path / "media",
                )

        # The original DB is back, and the stale WAL did not come back with it.
        assert _bodies(live) == ["old"]
        assert not Path(f"{live}-wal").exists()


class TestArchiveSidecarsInstalled:
    async def test_archive_wal_is_installed_and_replayed(self, tmp_path: Path) -> None:
        """Data that lived only in the archived WAL comes back."""
        live = _make_db(tmp_path / "live.db", body="old")
        source, wal, shm = _wal_archive_pair(tmp_path / "archived.db", body="from-the-wal")

        await _restore(
            tmp_path,
            _archive(tmp_path, source.read_bytes(), wal=wal, shm=shm),
            live,
        )

        # The sidecars were carried across ...
        assert Path(f"{live}-wal").read_bytes() == wal
        assert Path(f"{live}-shm").read_bytes() == shm
        # ... and replaying them yields the commit the main file never had.
        assert "from-the-wal" in _bodies(live)

    async def test_validation_keeps_only_real_sidecars(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "a.db")
        junk = tmp_path / "junk-wal"
        junk.write_bytes(b"definitely not a wal file")

        plan = validate_restore_candidate(db, junk, None)
        assert plan == _SidecarPlan(wal=None, shm=None)

    async def test_sidecar_with_bad_header_is_not_installed(self, tmp_path: Path) -> None:
        live = _make_db(tmp_path / "live.db", body="old")
        source = _make_db(tmp_path / "archived.db", body="new")

        await _restore(
            tmp_path,
            _archive(tmp_path, source.read_bytes(), wal=b"garbage-with-no-sqlite-header"),
            live,
        )

        assert not Path(f"{live}-wal").exists()
        assert _bodies(live) == ["new"]

    async def test_validation_covers_the_pair_not_just_the_main_file(
        self, tmp_path: Path
    ) -> None:
        """A main file whose schema exists only in the WAL must still validate.

        This is the whole reason validation happens on a scratch copy with the
        sidecars in place: checking the main file alone would reject exactly
        the archives the sidecar support exists for (the checkpoint never
        finished, so the newest schema/data is WAL-only), and checking it in
        the extraction dir would destroy the sidecars we are about to install.
        """
        source, wal, _shm = _wal_archive_pair(tmp_path / "archived.db", body="from-the-wal")
        main_only = tmp_path / "main-only.db"
        main_only.write_bytes(source.read_bytes())
        wal_file = tmp_path / "archived.db-wal"
        wal_file.write_bytes(wal)

        from app.core.restore import validate_extracted_db

        with pytest.raises(ValueError, match="missing expected tables"):
            validate_extracted_db(main_only)

        plan = validate_restore_candidate(main_only, wal_file, None)
        assert plan.wal == wal_file

    async def test_no_sidecars_validates_directly(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "plain.db")
        assert validate_restore_candidate(db, None, None).any is False


class TestImportEndpointSidecars:
    async def test_import_installs_archive_sidecars(
        self, client, tmp_path: Path, monkeypatch
    ) -> None:
        """POST /backup/import carries the archive's WAL through to the live DB."""
        import app.core.config as config_mod
        import app.core.database as dbmod

        async def _noop() -> None:
            return None

        monkeypatch.setattr(dbmod, "init_db", _noop)

        live = _make_db(tmp_path / "live.db", body="old")
        monkeypatch.setattr(
            config_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{live}", raising=False
        )

        source, wal, shm = _wal_archive_pair(tmp_path / "archived.db", body="from-the-wal")
        archive = _archive(tmp_path, source.read_bytes(), wal=wal, shm=shm)

        r = await client.post(
            "/api/v1/backup/import",
            files={"file": ("backup.tar.gz", archive.read_bytes(), "application/gzip")},
        )

        assert r.status_code == 200
        assert Path(f"{live}-wal").read_bytes() == wal
        assert "from-the-wal" in _bodies(live)
