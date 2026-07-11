"""Integration tests for the email module (accounts, folders, messages, attachments).

The IMAP/SMTP round-trips (sync, send, flag push) need a real mailbox, so the
tests exercise the local DB paths directly. Account payloads use a fail-fast
host (``127.0.0.1:1`` → immediate ECONNREFUSED) so any best-effort server-side
op returns promptly without a connection.
"""

from datetime import datetime, timezone

import app.routers.email as email_router
from app.models.email_folder import EmailFolder
from app.models.email_message import EmailMessage

# Fail-fast mailbox: connecting to a closed port refuses immediately, so the
# best-effort IMAP/SMTP calls in flag-push/delete return at once.
ACCOUNT = {
    "label": "Test",
    "email_address": "owner@example.com",
    "imap_host": "127.0.0.1",
    "imap_port": 1,
    "imap_use_ssl": False,
    "smtp_host": "127.0.0.1",
    "smtp_port": 1,
    "smtp_use_tls": False,
    "username": "owner@example.com",
    "password": "secret",
}


async def _seed_message(client, db_session):
    """Create an account + folder + one message directly in the DB."""
    acct = (await client.post("/api/v1/email/accounts", json=ACCOUNT)).json()
    folder = EmailFolder(
        account_id=acct["id"],
        folder_name="INBOX",
        display_name="INBOX",
        special_use="inbox",
        sync_enabled=True,
    )
    db_session.add(folder)
    await db_session.commit()
    await db_session.refresh(folder)
    msg = EmailMessage(
        account_id=acct["id"],
        folder_id=folder.id,
        uid=1,
        from_address="friend@example.com",
        from_name="Friend",
        to_addresses=[{"address": "owner@example.com", "name": None}],
        subject="Hello",
        snippet="Hi there",
        text_body="Hi there",
        sent_at=datetime.now(timezone.utc),
        is_read=False,
        is_starred=False,
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return acct, folder, msg


class TestEmailAccounts:
    async def test_create_get_list_update_delete(self, client):
        resp = await client.post("/api/v1/email/accounts", json=ACCOUNT)
        assert resp.status_code == 201
        acct = resp.json()
        assert acct["email_address"] == "owner@example.com"
        assert acct["label"] == "Test"
        # Password must never be serialized to the client.
        assert "password" not in resp.text
        assert "password_encrypted" not in acct

        one = await client.get(f"/api/v1/email/accounts/{acct['id']}")
        assert one.status_code == 200
        assert one.json()["id"] == acct["id"]

        listing = await client.get("/api/v1/email/accounts")
        assert listing.status_code == 200
        assert any(a["id"] == acct["id"] for a in listing.json())

        upd = await client.put(
            f"/api/v1/email/accounts/{acct['id']}", json={"label": "Renamed"}
        )
        assert upd.status_code == 200
        assert upd.json()["label"] == "Renamed"

        dele = await client.delete(f"/api/v1/email/accounts/{acct['id']}")
        assert dele.status_code == 204

    async def test_get_missing_account_404(self, client):
        resp = await client.get("/api/v1/email/accounts/99999")
        assert resp.status_code == 404


class TestEmailFolders:
    async def test_cached_folders(self, client, db_session):
        acct = await client.post("/api/v1/email/accounts", json=ACCOUNT)
        aid = acct.json()["id"]

        # No server round-trip: the cached list is empty before discovery.
        empty = await client.get(f"/api/v1/email/accounts/{aid}/folders")
        assert empty.status_code == 200
        assert empty.json() == []

        db_session.add(
            EmailFolder(
                account_id=aid,
                folder_name="INBOX",
                display_name="INBOX",
                special_use="inbox",
                sync_enabled=True,
            )
        )
        await db_session.commit()

        cached = await client.get(f"/api/v1/email/accounts/{aid}/folders")
        assert cached.status_code == 200
        body = cached.json()
        assert len(body) == 1
        assert body[0]["folder_name"] == "INBOX"
        assert body[0]["special_use"] == "inbox"


class TestEmailMessages:
    async def test_list_get_and_404(self, client, db_session):
        _acct, _folder, msg = await _seed_message(client, db_session)

        listing = await client.get("/api/v1/email/messages")
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] == 1
        assert body["items"][0]["subject"] == "Hello"

        one = await client.get(f"/api/v1/email/messages/{msg.id}")
        assert one.status_code == 200
        detail = one.json()
        assert detail["text_body"] == "Hi there"
        assert detail["from_address"] == "friend@example.com"
        assert detail["attachments"] == []

        missing = await client.get("/api/v1/email/messages/99999")
        assert missing.status_code == 404

    async def test_filter_and_flags(self, client, db_session):
        _acct, _folder, msg = await _seed_message(client, db_session)

        unread = await client.get("/api/v1/email/messages?unread_only=true")
        assert unread.json()["total"] == 1

        # Mark read — IMAP push fails fast against 127.0.0.1:1 but is swallowed.
        flagged = await client.patch(
            f"/api/v1/email/messages/{msg.id}/flags", json={"is_read": True}
        )
        assert flagged.status_code == 200
        assert flagged.json()["is_read"] is True

        unread2 = await client.get("/api/v1/email/messages?unread_only=true")
        assert unread2.json()["total"] == 0

    async def test_search(self, client, db_session):
        _acct, _folder, _msg = await _seed_message(client, db_session)
        found = await client.get("/api/v1/email/messages?search=hello")
        assert found.json()["total"] == 1
        none = await client.get("/api/v1/email/messages?search=nomatch")
        assert none.json()["total"] == 0

    async def test_account_scoping(self, client, db_session):
        acct, _folder, _msg = await _seed_message(client, db_session)
        scoped = await client.get(f"/api/v1/email/messages?account_id={acct['id']}")
        assert scoped.json()["total"] == 1
        other = await client.get("/api/v1/email/messages?account_id=99999")
        assert other.json()["total"] == 0


class TestEmailAttachments:
    async def test_upload_temp_attachment(self, client):
        files = {"file": ("note.txt", b"hello world", "text/plain")}
        resp = await client.post("/api/v1/email/attachments", files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "note.txt"
        assert body["file_size"] == len(b"hello world")
        assert body["id"]

    async def test_oversize_attachment_rejected(self, client, monkeypatch):
        monkeypatch.setattr(
            email_router.settings, "EMAIL_MAX_ATTACHMENT_SIZE_BYTES", 5
        )
        files = {"file": ("big.txt", b"x" * 20, "text/plain")}
        resp = await client.post("/api/v1/email/attachments", files=files)
        assert resp.status_code == 400
