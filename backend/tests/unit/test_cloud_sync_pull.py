"""CloudSyncService.pull — last-writer-wins merge of remote entry ops.

Uses an in-memory fake provider (no network) so the merge logic — path parsing,
per-entity op selection, LWW against the local row, and encrypted round-trip —
is exercised end-to-end.
"""

import json
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.services.cloud_sync_service import CloudSyncService, parse_sync_path


class _FakeProvider:
    """Minimal SyncProvider over an in-memory {path: bytes} map."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def list_files(self, prefix: str) -> list[str]:
        return [p for p in self._files if p.startswith(prefix)]

    async def download(self, path: str) -> bytes:
        return self._files[path]

    async def close(self) -> None:
        return None


def _entry_payload(eid: int, **over: object) -> bytes:
    base: dict[str, object] = {
        "id": eid,
        "entry_date": "2026-01-01",
        "title": "t",
        "body": "b",
        "updated_at": "2026-01-01T00:00:00",
    }
    base.update(over)
    return json.dumps(base).encode()


class TestParseSyncPath:
    def test_parses_op_path(self) -> None:
        assert parse_sync_path("lifelogr/entry/5/update.json") == ("entry", 5, "update")

    def test_skips_backup_archives(self) -> None:
        assert parse_sync_path("lifelogr-backup-2026.tar.gz") is None

    def test_skips_non_json_and_bad_ops(self) -> None:
        assert parse_sync_path("lifelogr/entry/5/update") is None
        assert parse_sync_path("lifelogr/entry/5/frobnicate.json") is None


class TestPullMerge:
    async def test_create_then_update_applies_latest(self, db_session: AsyncSession) -> None:
        files = {
            "lifelogr/entry/1/create.json": _entry_payload(1, body="old", updated_at="2026-01-01T00:00:00"),
            "lifelogr/entry/1/update.json": _entry_payload(1, body="new", updated_at="2026-01-02T00:00:00"),
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        e = await db_session.get(Entry, 1)
        assert e is not None and e.body == "new"

    async def test_delete_soft_deletes_when_newer(self, db_session: AsyncSession) -> None:
        db_session.add(
            Entry(id=2, entry_date=date(2026, 1, 1), body="x", updated_at=datetime(2025, 1, 1))
        )
        await db_session.commit()
        files = {"lifelogr/entry/2/delete.json": _entry_payload(2, updated_at="2026-06-01T00:00:00")}
        await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert (await db_session.get(Entry, 2)).is_deleted is True

    async def test_lww_local_newer_is_kept(self, db_session: AsyncSession) -> None:
        db_session.add(
            Entry(id=3, entry_date=date(2026, 1, 1), body="local", updated_at=datetime(2026, 7, 1))
        )
        await db_session.commit()
        files = {"lifelogr/entry/3/update.json": _entry_payload(3, body="remote", updated_at="2026-01-01T00:00:00")}
        await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert (await db_session.get(Entry, 3)).body == "local"

    async def test_lww_remote_newer_overwrites(self, db_session: AsyncSession) -> None:
        db_session.add(
            Entry(id=4, entry_date=date(2026, 1, 1), body="local", updated_at=datetime(2020, 1, 1))
        )
        await db_session.commit()
        files = {"lifelogr/entry/4/update.json": _entry_payload(4, body="remote", updated_at="2026-05-01T00:00:00")}
        await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert (await db_session.get(Entry, 4)).body == "remote"

    async def test_skips_media_and_stray_files(self, db_session: AsyncSession) -> None:
        files = {
            "lifelogr/entry/5/create.json": _entry_payload(5, body="e5"),
            "lifelogr/media/9/create.json": json.dumps({"id": 9}).encode(),
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        assert result["skipped"] == 1
        assert await db_session.get(Entry, 5) is not None

    async def test_encrypted_round_trip(self, db_session: AsyncSession) -> None:
        from app.services.encryption_service import EncryptionService

        key = EncryptionService._derive_key("test-pass")
        cipher = EncryptionService._encrypt(_entry_payload(6, body="enc"), key).encode()
        files = {"lifelogr/entry/6/create.json": cipher}
        await CloudSyncService(db_session, _FakeProvider(files)).pull(passphrase="test-pass")
        await db_session.commit()
        e = await db_session.get(Entry, 6)
        assert e is not None and e.body == "enc"
