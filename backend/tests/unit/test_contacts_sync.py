"""Unit tests for two-way Google Contacts (People API) sync (mocked API)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.security import encrypt
from app.models.contact import Contact
from app.models.google_sync import GoogleSyncAccount
from app.services.contacts_sync_service import ContactsSyncService


class FakeResponse:
    def __init__(self, payload: dict | list, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> dict | list:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            resp = httpx.Response(self.status_code, request=httpx.Request("GET", "http://x"))
            raise httpx.HTTPStatusError("err", request=resp.request, response=resp)


class FakeAPI:
    """Stand-in for GoogleAPIClient; records params + body + if_match.

    Faithfully calls ``raise_for_status`` (like the real client) so 4xx scripted
    responses surface as ``httpx.HTTPStatusError`` — the 412/404 branches depend on it.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._script: dict[str, FakeResponse] = {}

    def script(self, key: str, payload: dict | list, status: int = 200) -> None:
        self._script[key] = FakeResponse(payload, status)

    async def request(self, method, url, *, params=None, json_body=None, headers=None, timeout=20.0, if_match=None):  # type: ignore[no-untyped-def]
        rec = {
            "method": method,
            "url": url,
            "params": params,
            "json_body": json_body,
            "if_match": if_match,
        }
        self.calls.append(rec)
        for key, resp in self._script.items():
            if key in url:
                resp.raise_for_status()  # mimic the real client
                return resp
        return FakeResponse({})

    async def __aenter__(self) -> FakeAPI:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass


def _person(
    resource_name: str,
    *,
    name: str | None = "Jane",
    email: str | None = "jane@example.com",
    phones: list[dict] | None = None,
    deleted: bool = False,
    etag: str = "etag1",
) -> dict:
    p: dict = {"resourceName": resource_name, "etag": etag}
    if deleted:
        p["metadata"] = {"deleted": True}
        return p
    if name is not None:
        p["names"] = [{"displayName": name, "metadata": {"primary": True}}]
    if email is not None:
        p["emailAddresses"] = [{"value": email, "metadata": {"primary": True}}]
    if phones:
        p["phoneNumbers"] = phones
    return p


def _svc(db_session, *, contacts_enabled: bool = True, token: str | None = None) -> ContactsSyncService:
    acct = GoogleSyncAccount(
        credentials_encrypted="x",
        contacts_enabled=contacts_enabled,
        contacts_sync_token=token,
    )
    return ContactsSyncService(db_session, acct, FakeAPI())


@pytest.mark.asyncio
async def test_pull_creates_then_updates_no_duplicate(db_session):
    svc = _svc(db_session, token="t")
    await svc._apply_person(_person("people/c1", name="Jane", email="jane@x.com", etag="e1"))
    await db_session.commit()
    rows = (await db_session.execute(select(Contact))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "google"
    assert rows[0].external_id == "people/c1"
    assert rows[0].name == "Jane"
    assert rows[0].email == "jane@x.com"
    assert rows[0].synced_at == rows[0].updated_at

    # Re-apply (incremental re-pull) — update in place, no duplicate.
    await svc._apply_person(_person("people/c1", name="Janet", email="jane@x.com", etag="e2"))
    await db_session.commit()
    rows = (await db_session.execute(select(Contact))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Janet"
    assert rows[0].etag == "e2"


@pytest.mark.asyncio
async def test_pull_email_collision_isolates_curated_contact(db_session):
    svc = _svc(db_session)
    # A curated manual contact already owns this email.
    db_session.add(Contact(name="Curated", email="dup@x.com", source="manual"))
    await db_session.commit()

    await svc._apply_person(_person("people/c2", name="Google Dup", email="DUP@x.com"))
    await db_session.commit()

    rows = (await db_session.execute(select(Contact))).scalars().all()
    assert len(rows) == 2  # curated untouched + new isolated google row
    google = await db_session.scalar(select(Contact).where(Contact.source == "google"))
    assert google.email == "g:people/c2@contacts.local"  # isolated, not clobbering
    manual = await db_session.scalar(select(Contact).where(Contact.source == "manual"))
    assert manual.name == "Curated" and manual.email == "dup@x.com"


@pytest.mark.asyncio
async def test_pull_email_less_synthesizes_placeholder(db_session):
    svc = _svc(db_session)
    await svc._apply_person(
        _person("people/c3", name="Phone Only", email=None, phones=[{"value": "+1555", "type": "mobile"}])
    )
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.source == "google"))
    assert row.email == "g:people/c3@contacts.local"
    assert row.name == "Phone Only"
    assert row.phone == "+1555"
    assert row.phones == [{"type": "mobile", "value": "+1555"}]


@pytest.mark.asyncio
async def test_pull_deletion_marker_soft_deletes(db_session):
    svc = _svc(db_session)
    await svc._apply_person(_person("people/c4", name="Gone", email="g@x.com"))
    await db_session.commit()
    assert (
        await db_session.scalar(select(Contact).where(Contact.external_id == "people/c4"))
    ).is_deleted is False

    await svc._apply_person(_person("people/c4", deleted=True))
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.external_id == "people/c4"))
    assert row.is_deleted is True
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_push_update_sends_body_etag_and_marks_synced(db_session):
    api = FakeAPI()
    api.script("people/c5:updateContact", {"etag": "etag-new"})
    acct = GoogleSyncAccount(credentials_encrypted="x", contacts_enabled=True, contacts_sync_token="t")
    svc = ContactsSyncService(db_session, acct, api)
    await svc._apply_person(_person("people/c5", name="Old", email="c5@x.com", etag="etag-old"))
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.external_id == "people/c5"))
    row.name = "New"
    row.updated_at = datetime(2030, 1, 1)  # force updated_at > synced_at
    await db_session.commit()

    stats = await svc._push()
    patches = [c for c in api.calls if c["method"] == "PATCH"]
    assert len(patches) == 1
    assert "updateContact" in patches[0]["url"]
    # People API: etag in the BODY (not an If-Match header), and updatePersonFields required.
    assert patches[0]["json_body"]["etag"] == "etag-old"
    assert patches[0]["if_match"] is None
    assert patches[0]["params"] == {
        "updatePersonFields": (
            "names,emailAddresses,phoneNumbers,organizations,nicknames,"
            "biographies,urls,imClients,addresses"
        )
    }
    assert stats["updated"] == 1
    await db_session.refresh(row)
    assert row.etag == "etag-new"


@pytest.mark.asyncio
async def test_push_412_conflict_refetches_remote_wins(db_session):
    api = FakeAPI()
    api.script("people/c6:updateContact", {}, status=412)
    api.script("people/c6", _person("people/c6", name="Remote Wins", email="c6@x.com", etag="etag-remote"))
    acct = GoogleSyncAccount(credentials_encrypted="x", contacts_enabled=True, contacts_sync_token="t")
    svc = ContactsSyncService(db_session, acct, api)
    await svc._apply_person(_person("people/c6", name="Local Edit", email="c6@x.com", etag="etag-old"))
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.external_id == "people/c6"))
    row.updated_at = datetime(2030, 1, 1)  # locally changed
    await db_session.commit()

    stats = await svc._push()
    assert stats["conflicts"] == 1
    await db_session.refresh(row)
    assert row.name == "Remote Wins"  # remote overwrote the local edit
    assert row.etag == "etag-remote"


@pytest.mark.asyncio
async def test_push_deletion_calls_deletecontact_and_clears_external_id(db_session):
    api = FakeAPI()
    acct = GoogleSyncAccount(credentials_encrypted="x", contacts_enabled=True, contacts_sync_token="t")
    svc = ContactsSyncService(db_session, acct, api)
    await svc._apply_person(_person("people/c7", name="Bye", email="c7@x.com"))
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.external_id == "people/c7"))
    row.is_deleted = True
    row.deleted_at = datetime.now()
    await db_session.commit()

    stats = await svc._push()
    deletes = [c for c in api.calls if c["method"] == "DELETE"]
    assert len(deletes) == 1
    assert "deleteContact" in deletes[0]["url"]
    assert stats["deleted"] == 1
    await db_session.refresh(row)
    assert row.external_id is None
    assert row.etag is None


@pytest.mark.asyncio
async def test_push_deletion_tolerates_already_gone_404(db_session):
    api = FakeAPI()
    api.script("people/c8:deleteContact", {}, status=404)
    acct = GoogleSyncAccount(credentials_encrypted="x", contacts_enabled=True, contacts_sync_token="t")
    svc = ContactsSyncService(db_session, acct, api)
    await svc._apply_person(_person("people/c8", name="Gone", email="c8@x.com"))
    await db_session.commit()
    row = await db_session.scalar(select(Contact).where(Contact.external_id == "people/c8"))
    row.is_deleted = True
    row.deleted_at = datetime.now()
    await db_session.commit()

    stats = await svc._push()
    assert stats["deleted"] == 1  # 404 treated as deleted
    await db_session.refresh(row)
    assert row.external_id is None


@pytest.mark.asyncio
async def test_push_skips_manual_and_unchanged(db_session):
    api = FakeAPI()
    acct = GoogleSyncAccount(credentials_encrypted="x", contacts_enabled=True, contacts_sync_token="t")
    svc = ContactsSyncService(db_session, acct, api)
    # A manual contact — never pushed.
    db_session.add(Contact(name="Manual", email="m@x.com", source="manual"))
    # A freshly-pulled google contact (synced_at == updated_at) — unchanged.
    await svc._apply_person(_person("people/c9", name="Fresh", email="c9@x.com"))
    await db_session.commit()

    await svc._push()
    assert api.calls == []  # nothing to push


@pytest.mark.asyncio
async def test_contacts_disabled_is_skipped(db_session):
    svc = _svc(db_session, contacts_enabled=False)
    result = await svc.sync()
    assert result == {"skipped": "contacts disabled"}
    assert svc.api.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_orchestrator_isolates_contacts_failure(db_session, monkeypatch):
    """A failing Contacts sync still lets Calendar + Tasks run; all are reported."""
    from app.services import google_sync_service as gss

    acct = GoogleSyncAccount(
        credentials_encrypted=encrypt('{"a":1}'),
        calendar_enabled=True,
        tasks_enabled=True,
        contacts_enabled=True,
    )
    db_session.add(acct)
    await db_session.commit()

    async def boom(self, *a, **k):
        raise RuntimeError("contacts down")

    monkeypatch.setattr(gss.CalendarSyncService, "sync", AsyncMock(return_value={"pulled": {}}))
    monkeypatch.setattr(gss.TasksSyncService, "sync", AsyncMock(return_value={"pulled": {}}))
    monkeypatch.setattr(gss.ContactsSyncService, "sync", boom)
    monkeypatch.setattr(gss, "GoogleAPIClient", lambda *a, **k: FakeAPI())

    result = await gss.GoogleSyncService(db_session).sync_all()
    assert "contacts down" in result["contacts"]["error"]
    assert result["calendar"] == {"pulled": {}}
    assert result["tasks"] == {"pulled": {}}
    await db_session.refresh(acct)
    assert acct.last_sync_error and "contacts down" in acct.last_sync_error
    assert acct.last_synced_at is not None
