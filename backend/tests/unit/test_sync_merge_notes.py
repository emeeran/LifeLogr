"""CloudSyncService.pull — merge of remote *note* ops, and enqueue rejection.

Notes follow the exact entry merge pattern (last-writer-wins on ``updated_at``,
soft delete, explicit ``updated_at`` write to beat ``onupdate``) plus
note-specific folder handling. The second half pins the enqueue contract: any
entity type pull cannot merge is rejected at the door with a 422, so nothing is
queued and then silently dropped.

Uses the in-memory fake provider from the entry pull tests' style (no network).
"""

import json
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note, NoteFolder
from app.services.cloud_sync_service import (
    SYNCABLE_ENTITY_TYPES,
    CloudSyncService,
    SyncService,
    UnsupportedSyncEntityType,
)


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


def _note_payload(nid: int, **over: object) -> bytes:
    base: dict[str, object] = {
        "id": nid,
        "title": "note",
        "body": "hello",
        "updated_at": "2026-01-01T00:00:00",
    }
    base.update(over)
    return json.dumps(base).encode()


@pytest.fixture
def sync_svc(db_session: AsyncSession) -> SyncService:
    return SyncService(db_session)


class TestNoteMerge:
    async def test_create_applies_new_note(self, db_session: AsyncSession) -> None:
        files = {"lifelogr/note/1/create.json": _note_payload(1, body="first")}
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result == {"pulled": 1, "skipped": 0}
        note = await db_session.get(Note, 1)
        assert note is not None and note.body == "first" and note.title == "note"

    async def test_update_conflict_remote_newer_wins(self, db_session: AsyncSession) -> None:
        db_session.add(Note(id=2, body="local", updated_at=datetime(2020, 1, 1)))
        await db_session.commit()
        files = {
            "lifelogr/note/2/update.json": _note_payload(
                2, body="remote", updated_at="2026-05-01T00:00:00"
            )
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        assert (await db_session.get(Note, 2)).body == "remote"

    async def test_update_conflict_local_newer_is_kept(self, db_session: AsyncSession) -> None:
        db_session.add(Note(id=3, body="local", updated_at=datetime(2026, 7, 1)))
        await db_session.commit()
        files = {
            "lifelogr/note/3/update.json": _note_payload(
                3, body="remote", updated_at="2026-01-01T00:00:00"
            )
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 0
        assert (await db_session.get(Note, 3)).body == "local"

    async def test_create_then_update_applies_latest_only(self, db_session: AsyncSession) -> None:
        files = {
            "lifelogr/note/4/create.json": _note_payload(4, body="old", updated_at="2026-01-01"),
            "lifelogr/note/4/update.json": _note_payload(4, body="new", updated_at="2026-01-02"),
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        assert (await db_session.get(Note, 4)).body == "new"

    async def test_delete_soft_deletes_and_respects_lww(
        self, db_session: AsyncSession
    ) -> None:
        db_session.add(Note(id=5, body="keep", updated_at=datetime(2026, 7, 1)))
        db_session.add(Note(id=6, body="gone", updated_at=datetime(2020, 1, 1)))
        await db_session.commit()
        files = {
            "lifelogr/note/5/delete.json": _note_payload(5, updated_at="2026-01-01"),
            "lifelogr/note/6/delete.json": _note_payload(6, updated_at="2026-06-01"),
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        newer = await db_session.get(Note, 5)
        assert newer is not None and newer.is_deleted is False  # local was newer
        older = await db_session.get(Note, 6)
        assert older is not None
        assert older.is_deleted is True and older.deleted_at is not None

    async def test_missing_folder_applies_unfiled(self, db_session: AsyncSession) -> None:
        """A folder this machine has never seen must not kill the whole op.

        Notes are hierarchical but folders are not synced, so the FK would fail;
        like entries ignore unknown tag ids, the note lands unfiled instead.
        """
        files = {"lifelogr/note/7/create.json": _note_payload(7, folder_id=4242)}
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result["pulled"] == 1
        note = await db_session.get(Note, 7)
        assert note is not None and note.folder_id is None

    async def test_known_folder_is_kept(self, db_session: AsyncSession) -> None:
        db_session.add(NoteFolder(id=10, name="Work"))
        await db_session.commit()
        files = {"lifelogr/note/8/create.json": _note_payload(8, folder_id=10, is_pinned=True)}
        await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        note = await db_session.get(Note, 8)
        assert note is not None
        assert note.folder_id == 10 and note.is_pinned is True

    async def test_encrypted_note_travels_with_its_salt(self, db_session: AsyncSession) -> None:
        payload = _note_payload(
            9,
            body="ciphertext",
            is_encrypted=True,
            encryption_salt="abc123",
            encrypted_at="2026-02-02T00:00:00",
        )
        files = {"lifelogr/note/9/create.json": payload}
        await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        note = await db_session.get(Note, 9)
        assert note is not None
        assert note.is_encrypted is True and note.encryption_salt == "abc123"

    async def test_legacy_remote_tag_op_is_skipped_not_applied(
        self, db_session: AsyncSession
    ) -> None:
        """Old clients could push tag ops; they are counted, warned, not applied."""
        files = {
            "lifelogr/tag/3/create.json": json.dumps({"id": 3, "name": "work"}).encode(),
            "lifelogr/note/1/create.json": _note_payload(1),
        }
        result = await CloudSyncService(db_session, _FakeProvider(files)).pull()
        await db_session.commit()
        assert result == {"pulled": 1, "skipped": 1}


class TestEnqueueRejection:
    """Enqueue must refuse entity types pull cannot merge — no silent drops."""

    async def test_tag_is_rejected(self, sync_svc: SyncService) -> None:
        with pytest.raises(UnsupportedSyncEntityType, match="hashtag"):
            await sync_svc.enqueue("create", "tag", 1, {"name": "work"})

    async def test_media_is_rejected(self, sync_svc: SyncService) -> None:
        with pytest.raises(UnsupportedSyncEntityType, match="media"):
            await sync_svc.enqueue("create", "media", 1, {"path": "x.png"})

    async def test_unknown_type_is_rejected(self, sync_svc: SyncService) -> None:
        with pytest.raises(UnsupportedSyncEntityType, match="unknown_thing"):
            await sync_svc.enqueue("create", "unknown_thing", 1, {})

    async def test_entry_and_note_still_enqueue(self, sync_svc: SyncService) -> None:
        for entity_type in SYNCABLE_ENTITY_TYPES:
            item = await sync_svc.enqueue("update", entity_type, 1, {"updated_at": "2026-01-01"})
            assert item.entity_type == entity_type

    async def test_enqueue_api_returns_422(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/sync/enqueue",
            json={"operation": "create", "entity_type": "tag", "entity_id": 1, "payload": {}},
        )
        assert r.status_code == 422
        assert "hashtag" in r.json()["detail"]
        # And nothing was queued.
        assert (await client.get("/api/v1/sync/pending")).json() == []

    async def test_enqueue_api_accepts_note(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/sync/enqueue",
            json={
                "operation": "update",
                "entity_type": "note",
                "entity_id": 1,
                "payload": {"body": "x", "updated_at": "2026-01-01T00:00:00"},
            },
        )
        assert r.status_code == 201
        assert r.json()["entity_type"] == "note"


def test_syncable_types_all_have_appliers() -> None:
    """Enqueue allowlist and pull dispatch table must stay in lockstep."""
    from app.services.cloud_sync_service import _ENTITY_APPLIERS

    assert set(SYNCABLE_ENTITY_TYPES) == set(_ENTITY_APPLIERS)
