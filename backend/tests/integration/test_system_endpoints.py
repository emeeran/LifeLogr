"""System endpoints: renderer-error intake and the shutdown guard.

The shutdown guard is what makes a window close wait for an in-flight backup
instead of killing the sidecar mid-upload.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.models.backup import BackupConfig, BackupSnapshot


async def test_client_error_is_accepted_and_deduplicated(client: AsyncClient) -> None:
    payload = {
        "message": "render exploded",
        "stack": "Error: render exploded\n    at Boom",
        "component": "EntryEditor",
        "url": "http://127.0.0.1:5173/journal?secret=1#frag",
        "view": "journal",
    }
    first = await client.post("/api/v1/system/client-errors", json=payload)
    assert first.status_code == 204
    # The same message+stack inside the window is dropped, still a no-op 204.
    second = await client.post("/api/v1/system/client-errors", json=payload)
    assert second.status_code == 204


async def test_client_error_rejects_oversized_message(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/system/client-errors", json={"message": "x" * 501}
    )
    assert r.status_code == 422


async def test_shutdown_state_is_idle_on_an_empty_database(client: AsyncClient) -> None:
    r = await client.get("/api/v1/system/shutdown-state")
    assert r.status_code == 200
    assert r.json() == {
        "busy": False,
        "reasons": [],
        "backups_in_progress": 0,
        "jobs": [],
    }


async def test_shutdown_state_reports_an_in_progress_backup(
    client: AsyncClient, db_session
) -> None:
    config = BackupConfig(
        provider="local_file", label="test", credentials_encrypted="{}"
    )
    db_session.add(config)
    await db_session.flush()
    db_session.add(BackupSnapshot(config_id=config.id, status="in_progress"))
    await db_session.commit()

    body = (await client.get("/api/v1/system/shutdown-state")).json()
    assert body["busy"] is True
    assert body["reasons"] == ["backup"]
    assert body["backups_in_progress"] == 1


async def test_completed_backup_does_not_block_shutdown(
    client: AsyncClient, db_session
) -> None:
    config = BackupConfig(
        provider="local_file", label="done", credentials_encrypted="{}"
    )
    db_session.add(config)
    await db_session.flush()
    db_session.add(BackupSnapshot(config_id=config.id, status="completed"))
    await db_session.commit()

    body = (await client.get("/api/v1/system/shutdown-state")).json()
    assert body["busy"] is False
    assert body["reasons"] == []
