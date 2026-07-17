"""Two-way Google Contacts (People API) sync.

Pull: list the account's connections — a full listing on the first run, and
incremental thereafter via Google's ``syncToken`` (which reports deletions as
people carrying ``metadata.deleted=true``). Connections are upserted into
``Contact`` keyed by ``external_id`` (the People ``resourceName``,
``source='google'``); deletions soft-delete the local row.

Push: local edits to ``source='google'`` contacts (``updated_at > synced_at``)
are pushed back via ``people.updateContact`` — etag-guarded, but unlike
Calendar the etag travels in the request BODY (not an ``If-Match`` header); a
``412`` means the remote changed since our etag, so we re-fetch and let the
remote copy win. Locally soft-deleted ``source='google'`` contacts are
``deleteContact``-ed on Google, then their ``external_id`` is cleared.

``source='manual'``/``'email'``/``'vcard'`` contacts are never pushed
(local-only stays local), mirroring Calendar/Tasks.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.services.google_oauth import GoogleAPIClient

logger = logging.getLogger(__name__)

_PEOPLE_BASE = "https://people.googleapis.com/v1"

# Person fields we read (pull) and write (push). The write set excludes
# ``metadata`` (read-only) and matches what ``_contact_to_person`` emits.
_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,nicknames,"
    "biographies,urls,imClients,addresses,metadata"
)
_UPDATE_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,nicknames,"
    "biographies,urls,imClients,addresses"
)


def _synth_email(resource_name: str) -> str:
    """A unique, clearly-machine placeholder for an email-less contact.

    ``resourceName`` is globally unique per account, so this is collision-free;
    the ``.local`` TLD keeps it from being a real address anyone mails.
    """
    return f"g:{resource_name}@contacts.local"


def _primary(items: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Primary item of a People multi-value list (first if none flagged)."""
    if not items:
        return None
    for it in items:
        if (it.get("metadata") or {}).get("primary"):
            return it
    return items[0]


def _emails_of(person: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for it in person.get("emailAddresses") or []:
        value = it.get("value")
        if value:
            out.append(value.strip().lower())
    return out


def _phones_of(
    person: dict[str, Any],
) -> tuple[str | None, str | None, list[dict[str, Any]] | None]:
    rich = [
        {"type": it.get("type", ""), "value": it.get("value", "")}
        for it in (person.get("phoneNumbers") or [])
        if it.get("value")
    ]
    if not rich:
        return None, None, None
    phone = rich[0]["value"]
    secondary = rich[1]["value"] if len(rich) > 1 else None
    return phone, secondary, rich


def _addresses_of(person: dict[str, Any]) -> list[dict[str, Any]] | None:
    out: list[dict[str, Any]] = []
    for a in person.get("addresses") or []:
        out.append(
            {
                "type": a.get("type", ""),
                "street": a.get("streetAddress", ""),
                "city": a.get("city", ""),
                "region": a.get("region", ""),
                "postal_code": a.get("postalCode", ""),
                "country": a.get("country", ""),
            }
        )
    return out or None


def _person_to_fields(person: dict[str, Any], resource_name: str) -> dict[str, Any]:
    """Map a People ``Person`` resource to local ``Contact`` column values."""
    name_obj = _primary(person.get("names"))
    name = (name_obj or {}).get("displayName")

    emails = _emails_of(person)
    if emails:
        email = emails[0]
        emails_extra = emails[1:] or None
    else:
        # Email-less contact → synthesize so the NOT NULL UNIQUE constraint holds.
        email = _synth_email(resource_name)
        emails_extra = None

    phone, phone_secondary, phones = _phones_of(person)

    org = _primary(person.get("organizations")) or {}
    nick = _primary(person.get("nicknames"))
    bio = _primary(person.get("biographies"))

    urls = [u["value"] for u in (person.get("urls") or []) if u.get("value")] or None
    ims = (
        [
            {"type": im.get("protocol", ""), "value": im.get("username", "")}
            for im in (person.get("imClients") or [])
            if im.get("username")
        ]
        or None
    )

    return {
        "name": name,
        "email": email,
        "emails_extra": emails_extra,
        "phone": phone,
        "phone_secondary": phone_secondary,
        "phones": phones,
        "company": (org or {}).get("name"),
        "title": (org or {}).get("title"),
        "department": (org or {}).get("department"),
        "nickname": (nick or {}).get("value"),
        "notes": (bio or {}).get("value"),
        "websites": urls,
        "im_handles": ims,
        "addresses": _addresses_of(person),
        "is_deleted": False,
        "deleted_at": None,
    }


def _contact_to_person(c: Contact) -> dict[str, Any]:
    """Map a local ``Contact`` to a People ``Person`` body for ``updateContact``."""
    names = [{"displayName": c.name}] if c.name else []
    emails: list[dict[str, Any]] = []
    if c.email and not c.email.endswith("@contacts.local"):
        emails.append({"value": c.email})
    for e in c.emails_extra or []:
        emails.append({"value": e})
    if c.phones:
        phones = [
            {"value": p.get("value", ""), "type": p.get("type", "")}
            for p in c.phones
            if p.get("value")
        ]
    else:
        phones = [{"value": c.phone}] if c.phone else []
        if c.phone_secondary:
            phones.append({"value": c.phone_secondary})
    organizations: list[dict[str, Any]] = []
    if c.company or c.title or c.department:
        organizations.append(
            {"name": c.company or "", "title": c.title or "", "department": c.department or ""}
        )
    addresses = [
        {
            "streetAddress": a.get("street", ""),
            "city": a.get("city", ""),
            "region": a.get("region", ""),
            "postalCode": a.get("postal_code", ""),
            "country": a.get("country", ""),
            "type": a.get("type", ""),
        }
        for a in (c.addresses or [])
    ]
    return {
        "names": names,
        "emailAddresses": emails,
        "phoneNumbers": phones,
        "organizations": organizations,
        "nicknames": [{"value": c.nickname}] if c.nickname else [],
        "biographies": [{"value": c.notes}] if c.notes else [],
        "urls": [{"value": u} for u in (c.websites or [])],
        "imClients": [
            {"protocol": im.get("type", ""), "username": im.get("value", "")}
            for im in (c.im_handles or [])
            if im.get("value")
        ],
        "addresses": addresses,
    }


class ContactsSyncService:
    """Two-way sync between a Google account's contacts and ``Contact``."""

    def __init__(self, db: AsyncSession, account: Any, api: GoogleAPIClient) -> None:
        self.db = db
        self.account = account
        self.api = api

    async def _mark_synced(self, obj: Contact) -> None:
        """Persist + reload the server-generated ``updated_at``, then mirror it.

        ``synced_at == updated_at`` marks a just-pulled row as not-locally-changed
        (push picks up ``updated_at > synced_at``). ``refresh`` (awaited) avoids
        the async lazy-load ``MissingGreenlet`` error on server-generated columns.
        """
        await self.db.flush()  # pending → persistent so refresh can reload it
        await self.db.refresh(obj)
        obj.synced_at = obj.updated_at

    async def sync(self) -> dict[str, Any]:
        if not self.account.contacts_enabled:
            return {"skipped": "contacts disabled"}
        try:
            pulled = await self._pull()
            pushed = await self._push()
            await self.db.commit()
            return {"pulled": pulled, "pushed": pushed}
        except Exception:
            await self.db.rollback()
            raise

    # ── Pull (Google → local) ────────────────────────────────────────────

    async def _pull(self) -> dict[str, int]:
        stats = {"contacts": 0}
        url = f"{_PEOPLE_BASE}/people/me/connections"
        params: dict[str, Any] = {"personFields": _PERSON_FIELDS}
        if self.account.contacts_sync_token:
            params["syncToken"] = self.account.contacts_sync_token
        else:
            params["requestSyncToken"] = "true"
        full_retry = False
        while True:
            try:
                resp = await self.api.request("GET", url, params=params)
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                # Sync tokens expire (410 Gone) → drop it and do one full re-sync.
                if exc.response.status_code == 410 and not full_retry:
                    logger.info("Contacts syncToken expired (410) — full re-sync")
                    self.account.contacts_sync_token = None
                    full_retry = True
                    params = {"personFields": _PERSON_FIELDS, "requestSyncToken": "true"}
                    continue
                raise
            for person in data.get("connections", []):
                await self._apply_person(person)
                stats["contacts"] += 1
            if data.get("nextSyncToken"):
                self.account.contacts_sync_token = data["nextSyncToken"]
            if data.get("nextPageToken"):
                params = {"personFields": _PERSON_FIELDS, "pageToken": data["nextPageToken"]}
                continue
            break
        return stats

    async def _apply_person(self, person: dict[str, Any]) -> None:
        resource_name = person.get("resourceName")
        if not resource_name:
            return
        # Deletion marker (incremental sync) → soft-delete locally.
        if (person.get("metadata") or {}).get("deleted"):
            existing = await self.db.scalar(
                select(Contact).where(
                    Contact.source == "google", Contact.external_id == resource_name
                )
            )
            if existing is not None and not existing.is_deleted:
                existing.is_deleted = True
                existing.deleted_at = datetime.now()
                await self._mark_synced(existing)
            return

        existing = await self._find_local(resource_name)
        fields = _person_to_fields(person, resource_name)
        if existing is None:
            # Creating: never clobber a curated contact that owns the same email.
            fields = await self._avoid_email_collision(resource_name, fields)
            existing = Contact(source="google", external_id=resource_name, **fields)
            self.db.add(existing)
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
        existing.etag = person.get("etag")
        await self._mark_synced(existing)

    async def _find_local(self, resource_name: str) -> Contact | None:
        """The local row for a Google person — keyed by (source, external_id)."""
        existing: Contact | None = await self.db.scalar(
            select(Contact).where(
                Contact.source == "google", Contact.external_id == resource_name
            )
        )
        return existing

    async def _avoid_email_collision(
        self, resource_name: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """If a real email is already owned by another row, isolate with a synth one."""
        email = fields["email"]
        if email == _synth_email(resource_name):
            return fields  # already machine-generated; resourceName is unique
        owner = await self.db.scalar(select(Contact).where(Contact.email == email))
        if owner is not None:
            fields["email"] = _synth_email(resource_name)
        return fields

    # ── Push (local → Google) ────────────────────────────────────────────

    async def _push(self) -> dict[str, int]:
        stats = {"updated": 0, "deleted": 0, "conflicts": 0}

        # 1. Deletions: source='google', soft-deleted, external_id still set.
        for c in (
            await self.db.scalars(
                select(Contact).where(
                    Contact.source == "google",
                    Contact.is_deleted == True,  # noqa: E712
                    Contact.external_id.isnot(None),
                )
            )
        ).all():
            try:
                await self.api.request(
                    "DELETE", f"{_PEOPLE_BASE}/{c.external_id}:deleteContact"
                )
                stats["deleted"] += 1
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 410):
                    stats["deleted"] += 1
                else:
                    logger.warning(
                        "Failed to delete Google contact %s", c.external_id, exc_info=True
                    )
            c.external_id = None
            c.etag = None

        # 2. Edits: source='google', not deleted, locally changed since last sync.
        for c in (
            await self.db.scalars(
                select(Contact).where(
                    Contact.source == "google",
                    Contact.is_deleted == False,  # noqa: E712
                    Contact.external_id.isnot(None),
                    Contact.synced_at.isnot(None),
                    Contact.updated_at > Contact.synced_at,
                )
            )
        ).all():
            body = _contact_to_person(c)
            body["etag"] = c.etag
            try:
                resp = await self.api.request(
                    "PATCH",
                    f"{_PEOPLE_BASE}/{c.external_id}:updateContact",
                    params={"updatePersonFields": _UPDATE_PERSON_FIELDS},
                    json_body=body,
                )
                c.etag = resp.json().get("etag")
                await self._mark_synced(c)
                stats["updated"] += 1
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 412:
                    # Remote changed since our etag → re-fetch, remote wins.
                    stats["conflicts"] += 1
                    logger.info("Conflict pushing contact %s — re-fetching", c.external_id)
                    await self._refetch_and_merge(c)
                else:
                    logger.warning(
                        "Failed to push Google contact %s", c.external_id, exc_info=True
                    )
        return stats

    async def _refetch_and_merge(self, c: Contact) -> None:
        """On a 412 conflict, overwrite the local row with the remote version."""
        try:
            resp = await self.api.request(
                "GET",
                f"{_PEOPLE_BASE}/{c.external_id}",
                params={"personFields": _PERSON_FIELDS},
            )
            person = resp.json()
        except Exception:
            logger.warning("Conflict re-fetch failed for %s", c.external_id, exc_info=True)
            return
        for key, value in _person_to_fields(person, c.external_id or "").items():
            setattr(c, key, value)
        c.etag = person.get("etag")
        await self._mark_synced(c)
