"""ContactService — CRUD, groups, vCard import/export, photos, and email auto-extraction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, MediaSizeError, NotFoundError
from app.models.contact import Contact
from app.models.contact_group import ContactGroup, contact_group_members
from app.models.email_message import EmailMessage
from app.schemas.contact import (
    ContactCreate,
    ContactGroupCreate,
    ContactGroupResponse,
    ContactGroupUpdate,
    ContactResponse,
    ContactUpdate,
    _normalize_email,
)

logger = logging.getLogger(__name__)

# Cap an uploaded contact photo at 8 MB — avatars should be small.
_PHOTO_MAX_BYTES = 8 * 1024 * 1024
_PHOTO_SUBDIR = "contacts"


# ── vCard 3.0 parse/serialize (stdlib only) ────────────────────────────────


def _unfold(text: str) -> list[str]:
    """Undo RFC 5545 line folding: continuation lines start with space/tab."""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t"):
            if lines:
                lines[-1] += raw[1:]
                continue
        lines.append(raw)
    return lines


def _split_property(line: str) -> tuple[str, str, dict[str, str]]:
    """Split a vCard property line into (NAME, value, params).

    Property form: NAME;PARAM=...;PARAM=...:VALUE — the first ':' separates
    name+params from value. Returns the uppercased NAME, the value, and a dict
    of lowercased params (e.g. ``{"type": "cell"}``).
    """
    if ":" not in line:
        return "", "", {}
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.lower()] = v.lower()
        else:
            # TYPE shorthand: TEL;CELL:... → {type: cell}
            params.setdefault("type", p.lower())
    return name, value, params


# Map vCard TEL TYPE → our phone type vocabulary.
_TEL_TYPE_MAP = {
    "cell": "mobile",
    "mobile": "mobile",
    "voice": "home",
    "home": "home",
    "work": "work",
    "fax": "fax",
    "pager": "pager",
}


def parse_vcard(text: str) -> list[dict[str, object]]:
    """Parse vCard text into a list of contact dicts.

    Each dict has keys: name, emails (list[str]), phones (list[str]),
    phones_typed (list[{type,value}]), addresses, websites, dates, im,
    nickname, company, title, notes, categories. Only vCard 3.0 fields we
    model are extracted. ``phones`` is kept as plain strings for backward
    compatibility; ``phones_typed`` carries the type label.
    """
    contacts: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    def _ensure(key: str) -> list:
        assert current is not None
        val = current.setdefault(key, [])
        return val  # type: ignore[return-value]

    for line in _unfold(text):
        name, value, params = _split_property(line)
        if name == "BEGIN" and value.upper() == "VCARD":
            current = {
                "emails": [],
                "phones": [],
                "phones_typed": [],
                "addresses": [],
                "websites": [],
                "dates": [],
                "im": [],
                "categories": [],
            }
            continue
        if name == "END" and value.upper() == "VCARD":
            if current is not None:
                contacts.append(current)
            current = None
            continue
        if current is None:
            continue
        if name == "FN":
            current["name"] = value
        elif name == "N" and "name" not in current:
            # N:Family;Given;Additional;Prefix;Suffix
            parts = value.split(";")
            given = parts[1] if len(parts) > 1 else ""
            family = parts[0] if parts else ""
            full = f"{given} {family}".strip()
            if full:
                current["name"] = full
        elif name == "NICKNAME":
            current["nickname"] = value
        elif name == "EMAIL":
            addr = value.strip().lower()
            if addr and addr not in current["emails"]:
                current["emails"].append(addr)
        elif name == "TEL":
            if value.strip():
                current["phones"].append(value.strip())
                tel_type = _TEL_TYPE_MAP.get(params.get("type", ""), "other")
                current["phones_typed"].append({"type": tel_type, "value": value.strip()})
        elif name == "ADR":
            # ADR;TYPE=home:POBox;Ext;Street;City;Region;Postal;Country
            bits = value.split(";")
            street = bits[2] if len(bits) > 2 else ""
            city = bits[3] if len(bits) > 3 else ""
            region = bits[4] if len(bits) > 4 else ""
            postal = bits[5] if len(bits) > 5 else ""
            country = bits[6] if len(bits) > 6 else ""
            if any([street, city, region, postal, country]):
                _ensure("addresses").append(
                    {
                        "type": params.get("type", "home"),
                        "street": street or None,
                        "city": city or None,
                        "region": region or None,
                        "postal_code": postal or None,
                        "country": country or None,
                    }
                )
        elif name == "URL":
            if value.strip():
                _ensure("websites").append(value.strip())
        elif name == "BDAY":
            raw = value.strip()[:10]  # accept YYYY-MM-DD (and prefix of more)
            if raw:
                _ensure("dates").append({"type": "birthday", "label": None, "date": raw})
        elif name in ("X-ANNIVERSARY", "ANNIVERSARY"):
            raw = value.strip()[:10]
            if raw:
                _ensure("dates").append({"type": "anniversary", "label": None, "date": raw})
        elif name in ("X-MS-IMADDRESS", "X-SKYPE", "X-JABBER", "IMPP"):
            if value.strip():
                _ensure("im").append({"type": params.get("type", "other"), "value": value.strip()})
        elif name == "ORG":
            current["company"] = value.split(";", 1)[0]
        elif name == "TITLE":
            current["title"] = value
        elif name == "CATEGORIES":
            for cat in value.split(","):
                cat = cat.strip()
                if cat:
                    _ensure("categories").append(cat)
        elif name == "NOTE":
            current["notes"] = value
    return contacts


def _fold_line(line: str, width: int = 75) -> str:
    """Fold a single property line to the RFC 5545 octet width."""
    if len(line.encode("utf-8")) <= width:
        return line
    out: list[str] = []
    chunk = ""
    for ch in line:
        if len((chunk + ch).encode("utf-8")) > width:
            out.append(chunk)
            chunk = ch
        else:
            chunk += ch
    if chunk:
        out.append(chunk)
    return "\r\n ".join(out)


def _tel_type_out(t: str) -> str:
    """Map our phone type back to a vCard TEL TYPE."""
    return {"mobile": "cell", "home": "voice", "work": "work", "fax": "fax", "pager": "pager"}.get(
        t, "voice"
    )


def serialize_vcard(c: Contact) -> str:
    """Serialize a single contact to a vCard 3.0 block.

    New structured fields are read via ``getattr`` defaults so legacy/stub
    objects (e.g. the unit-test ``_C``) keep serializing without error.
    """
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    fn = c.name or c.email
    lines.append(f"FN:{fn}")
    # N: best-effort split of name into family/given.
    if c.name:
        parts = c.name.rsplit(" ", 1)
        family = parts[-1] if len(parts) > 1 else c.name
        given = parts[0] if len(parts) > 1 else ""
        lines.append(f"N:{family};{given};;;")
    nickname = getattr(c, "nickname", None)
    if nickname:
        lines.append(f"NICKNAME:{nickname}")
    lines.append(f"EMAIL;TYPE=internet:{c.email}")
    for extra in c.emails_extra or []:
        lines.append(f"EMAIL;TYPE=internet:{extra}")

    phones = getattr(c, "phones", None)
    if phones:  # rich multi-value list is the source of truth when present
        for p in phones:
            t = _tel_type_out(p.get("type", "mobile")) if isinstance(p, dict) else "cell"
            v = p.get("value", "") if isinstance(p, dict) else str(p)
            if v:
                lines.append(f"TEL;TYPE={t}:{v}")
    else:  # fall back to legacy scalar columns
        if c.phone:
            lines.append(f"TEL;TYPE=cell:{c.phone}")
        if c.phone_secondary:
            lines.append(f"TEL;TYPE=home:{c.phone_secondary}")

    for addr in getattr(c, "addresses", None) or []:
        street = addr.get("street", "") if isinstance(addr, dict) else ""
        city = addr.get("city", "") if isinstance(addr, dict) else ""
        region = addr.get("region", "") if isinstance(addr, dict) else ""
        postal = addr.get("postal_code", "") if isinstance(addr, dict) else ""
        country = addr.get("country", "") if isinstance(addr, dict) else ""
        atype = addr.get("type", "home") if isinstance(addr, dict) else "home"
        lines.append(
            f"ADR;TYPE={atype};;{street};{city};{region};{postal};{country}"
        )
    for site in getattr(c, "websites", None) or []:
        lines.append(f"URL:{site}")
    for d in getattr(c, "dates", None) or []:
        dtype = d.get("type", "birthday") if isinstance(d, dict) else "birthday"
        dval = d.get("date", "") if isinstance(d, dict) else str(d)
        if dtype == "anniversary":
            lines.append(f"X-ANNIVERSARY:{dval}")
        elif dval:
            lines.append(f"BDAY:{dval}")
    for im in getattr(c, "im_handles", None) or []:
        v = im.get("value", "") if isinstance(im, dict) else str(im)
        if v:
            lines.append(f"IMPP;TYPE={im.get('type', 'other') if isinstance(im, dict) else 'other'}:{v}")
    if c.company:
        lines.append(f"ORG:{c.company}")
    if c.title:
        lines.append(f"TITLE:{c.title}")
    groups = getattr(c, "groups", None) or []
    if groups:
        names = [g.name for g in groups]
        lines.append(f"CATEGORIES:{','.join(names)}")
    if c.notes:
        note_val = c.notes.replace("\n", "\\n")
        lines.append(f"NOTE:{note_val}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold_line(ln) for ln in lines)


# ── Service ────────────────────────────────────────────────────────────────


def contact_to_response(c: Contact) -> ContactResponse:
    """Build a ContactResponse, hydrating phones from legacy columns.

    Reads must NOT mutate the ORM object: assigning to ``c.phones`` would mark
    the row dirty, and a subsequent query (e.g. the list ``count``) would
    autoflush it — firing ``updated_at``'s ``onupdate`` and invalidating that
    server-generated column, so the following *synchronous* ``model_validate``
    would raise MissingGreenlet when reading ``updated_at``. We instead build
    the response from a plain dict and synthesize phones without touching the
    instance, so the session stays clean.
    """
    data = {field: getattr(c, field) for field in ContactResponse.model_fields}
    if data.get("phones") is None and (c.phone or c.phone_secondary):
        synth: list[dict[str, str]] = []
        if c.phone:
            synth.append({"type": "mobile", "value": c.phone})
        if c.phone_secondary:
            synth.append({"type": "home", "value": c.phone_secondary})
        data["phones"] = synth
    return ContactResponse(**data)


class ContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, contact_id: int, include_deleted: bool = False) -> Contact:
        stmt = select(Contact).where(Contact.id == contact_id)
        if not include_deleted:
            stmt = stmt.where(Contact.is_deleted == False)  # noqa: E712
        contact = (await self.db.execute(stmt)).scalar_one_or_none()
        if not contact:
            raise NotFoundError(f"Contact {contact_id} not found")
        return contact

    async def _reload(self, contact_id: int) -> Contact:
        """Re-fetch a contact so its selectin ``groups`` relationship is loaded.

        ``Session.refresh()`` reloads column attributes but not selectin
        relationships, so a plain refresh leaves ``contact.groups`` unloaded —
        and accessing it during sync Pydantic validation raises MissingGreenlet.
        A fresh ``select(Contact)`` re-runs the selectin load.
        ``populate_existing=True`` forces the relationship collection to be
        re-read even when the instance is already cached in the identity map
        (e.g. update-then-read within one session) — critical because group
        membership is changed via direct table writes, not the ORM collection.
        """
        contact = (
            await self.db.execute(
                select(Contact)
                .where(Contact.id == contact_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if contact is None:
            raise NotFoundError(f"Contact {contact_id} not found")
        return contact

    @staticmethod
    def _apply_phones(contact: Contact, data: ContactCreate | ContactUpdate) -> None:
        """Mirror the rich phones list into the legacy scalar columns."""
        phones = getattr(data, "phones", None)
        if phones is not None:
            contact.phones = [p.model_dump() for p in phones] or None
            contact.phone = phones[0].value if phones else None
            contact.phone_secondary = phones[1].value if len(phones) > 1 else None

    async def _set_groups(self, contact: Contact, group_ids: list[int] | None) -> None:
        """Reconcile group membership to exactly ``group_ids`` (existing groups only)."""
        if group_ids is None:
            return
        await self._replace_memberships(contact.id, group_ids)

    async def _replace_memberships(self, contact_id: int, group_ids: list[int]) -> None:
        """Set a contact's group memberships directly on the association table.

        Manipulating the join table directly (rather than assigning
        ``contact.groups = [...]``) avoids triggering a lazy-load of the
        relationship collection in a synchronous context (MissingGreenlet).
        The selectin ``groups`` relationship is re-read on the next query.
        """
        await self.db.execute(
            delete(contact_group_members).where(
                contact_group_members.c.contact_id == contact_id
            )
        )
        if not group_ids:
            return
        result = await self.db.execute(
            select(ContactGroup.id).where(ContactGroup.id.in_(group_ids))
        )
        valid_ids = [row[0] for row in result.all()]
        if valid_ids:
            await self.db.execute(
                contact_group_members.insert(),
                [{"contact_id": contact_id, "group_id": gid} for gid in valid_ids],
            )

    async def create(self, data: ContactCreate) -> Contact:
        email = _normalize_email(str(data.email))
        await self._assert_unique(email)
        contact = Contact(
            name=data.name,
            email=email,
            emails_extra=data.emails_extra,
            phone=data.phone,
            phone_secondary=data.phone_secondary,
            company=data.company,
            title=data.title,
            department=data.department,
            profession=data.profession,
            nickname=data.nickname,
            addresses=[a.model_dump() for a in data.addresses] if data.addresses else None,
            im_handles=[i.model_dump() for i in data.im_handles] if data.im_handles else None,
            websites=data.websites,
            dates=[d.model_dump() for d in data.dates] if data.dates else None,
            relationships=[r.model_dump() for r in data.relationships] if data.relationships else None,
            notes=data.notes,
            is_favorite=data.is_favorite,
            source="manual",
        )
        self._apply_phones(contact, data)
        self.db.add(contact)
        await self.db.flush()
        await self._set_groups(contact, data.group_ids)
        await self.db.commit()
        return await self._reload(contact.id)

    async def get(self, contact_id: int) -> Contact:
        return await self._get(contact_id)

    async def list_all(
        self,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
        group_id: int | None = None,
        favorites_only: bool = False,
    ) -> list[Contact]:
        stmt = select(Contact).where(Contact.is_deleted == False)  # noqa: E712
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    Contact.email.ilike(like),
                    Contact.name.ilike(like),
                    Contact.phone.ilike(like),
                    Contact.phone_secondary.ilike(like),
                    Contact.company.ilike(like),
                )
            )
        if favorites_only:
            stmt = stmt.where(Contact.is_favorite == True)  # noqa: E712
        if group_id is not None:
            # EXISTS subquery avoids row multiplication from the join.
            member = (
                select(contact_group_members.c.contact_id)
                .where(
                    contact_group_members.c.group_id == group_id,
                    contact_group_members.c.contact_id == Contact.id,
                )
                .exists()
            )
            stmt = stmt.where(member)
        stmt = stmt.order_by(Contact.name, Contact.email).offset(offset).limit(limit)
        rows = list((await self.db.execute(stmt)).scalars().all())
        return rows

    async def count(
        self,
        search: str | None = None,
        group_id: int | None = None,
        favorites_only: bool = False,
    ) -> int:
        """Total non-deleted contacts matching the optional filters."""
        stmt = select(func.count()).select_from(Contact).where(
            Contact.is_deleted == False  # noqa: E712
        )
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    Contact.email.ilike(like),
                    Contact.name.ilike(like),
                    Contact.phone.ilike(like),
                    Contact.phone_secondary.ilike(like),
                    Contact.company.ilike(like),
                )
            )
        if favorites_only:
            stmt = stmt.where(Contact.is_favorite == True)  # noqa: E712
        if group_id is not None:
            member = (
                select(contact_group_members.c.contact_id)
                .where(
                    contact_group_members.c.group_id == group_id,
                    contact_group_members.c.contact_id == Contact.id,
                )
                .exists()
            )
            stmt = stmt.where(member)
        return int((await self.db.execute(stmt)).scalar() or 0)

    async def update(self, contact_id: int, data: ContactUpdate) -> Contact:
        contact = await self._get(contact_id)
        if data.email is not None:
            new_email = _normalize_email(str(data.email))
            if new_email != contact.email:
                await self._assert_unique(new_email, exclude_id=contact_id)
            contact.email = new_email
        if data.name is not None:
            contact.name = data.name
        if data.emails_extra is not None:
            contact.emails_extra = data.emails_extra
        if data.phone_secondary is not None:
            contact.phone_secondary = data.phone_secondary
        if data.company is not None:
            contact.company = data.company
        if data.title is not None:
            contact.title = data.title
        if data.department is not None:
            contact.department = data.department
        if data.profession is not None:
            contact.profession = data.profession
        if data.nickname is not None:
            contact.nickname = data.nickname
        if data.addresses is not None:
            contact.addresses = [a.model_dump() for a in data.addresses] or None
        if data.im_handles is not None:
            contact.im_handles = [i.model_dump() for i in data.im_handles] or None
        if data.websites is not None:
            contact.websites = data.websites or None
        if data.dates is not None:
            contact.dates = [d.model_dump() for d in data.dates] or None
        if data.relationships is not None:
            contact.relationships = [r.model_dump() for r in data.relationships] or None
        if data.notes is not None:
            contact.notes = data.notes
        if data.is_favorite is not None:
            contact.is_favorite = data.is_favorite
        self._apply_phones(contact, data)
        await self._set_groups(contact, data.group_ids)
        await self.db.commit()
        return await self._reload(contact.id)

    async def delete(self, contact_id: int) -> None:
        contact = await self._get(contact_id)
        contact.is_deleted = True
        contact.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def restore(self, contact_id: int) -> Contact:
        contact = await self._get(contact_id, include_deleted=True)
        contact.is_deleted = False
        contact.deleted_at = None
        await self.db.commit()
        return await self._reload(contact.id)

    # ── Groups ─────────────────────────────────────────────────────────────

    async def _group_response(self, group: ContactGroup) -> ContactGroupResponse:
        # No back-reference relationship on ContactGroup (avoids an overlap with
        # Contact.groups); count members directly off the association table.
        count_stmt = (
            select(func.count())
            .select_from(contact_group_members)
            .where(contact_group_members.c.group_id == group.id)
        )
        member_count = int((await self.db.execute(count_stmt)).scalar() or 0)
        return ContactGroupResponse(
            id=group.id,
            name=group.name,
            color=group.color,
            sort_order=group.sort_order,
            member_count=member_count,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    async def list_groups(self) -> list[ContactGroupResponse]:
        stmt = select(ContactGroup).order_by(ContactGroup.sort_order, ContactGroup.name)
        groups = list((await self.db.execute(stmt)).scalars().all())
        return [await self._group_response(g) for g in groups]

    async def create_group(self, data: ContactGroupCreate) -> ContactGroupResponse:
        await self._assert_group_name_unique(data.name)
        group = ContactGroup(name=data.name, color=data.color, sort_order=data.sort_order)
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return await self._group_response(group)

    async def update_group(
        self, group_id: int, data: ContactGroupUpdate
    ) -> ContactGroupResponse:
        group = await self._get_group(group_id)
        if data.name is not None and data.name != group.name:
            await self._assert_group_name_unique(data.name, exclude_id=group_id)
            group.name = data.name
        if data.color is not None:
            group.color = data.color
        if data.sort_order is not None:
            group.sort_order = data.sort_order
        await self.db.commit()
        await self.db.refresh(group)
        return await self._group_response(group)

    async def delete_group(self, group_id: int) -> None:
        group = await self._get_group(group_id)
        await self.db.delete(group)
        await self.db.commit()

    async def _get_group(self, group_id: int) -> ContactGroup:
        group = (
            await self.db.execute(select(ContactGroup).where(ContactGroup.id == group_id))
        ).scalar_one_or_none()
        if not group:
            raise NotFoundError(f"Contact group {group_id} not found")
        return group

    async def _assert_group_name_unique(
        self, name: str, exclude_id: int | None = None
    ) -> None:
        stmt = select(ContactGroup.id).where(ContactGroup.name == name)
        if exclude_id is not None:
            stmt = stmt.where(ContactGroup.id != exclude_id)
        if (await self.db.execute(stmt)).scalar_one_or_none() is not None:
            raise ConflictError(f"A contact group named {name!r} already exists")

    # ── Related emails ─────────────────────────────────────────────────────

    async def related_emails(self, contact_id: int) -> list[EmailMessage]:
        """Emails whose from/to/cc involves any of this contact's addresses."""
        contact = await self._get(contact_id)
        addrs = {contact.email.lower()}
        for extra in contact.emails_extra or []:
            addrs.add(str(extra).strip().lower())
        addrs = {a for a in addrs if a and "@" in a}
        if not addrs:
            return []
        conds = []
        for a in addrs:
            conds.append(func.lower(EmailMessage.from_address) == a)
            conds.append(EmailMessage.to_addresses.like(f"%{a}%"))
            conds.append(EmailMessage.cc_addresses.like(f"%{a}%"))
        stmt = (
            select(EmailMessage)
            .where(or_(*conds))
            .order_by(EmailMessage.sent_at.desc())
            .limit(100)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Photo ──────────────────────────────────────────────────────────────

    async def set_photo(self, contact_id: int, data: bytes, filename: str) -> Contact:
        if len(data) > _PHOTO_MAX_BYTES:
            raise MediaSizeError("Contact photo must be under 8 MB")
        contact = await self._get(contact_id)
        ext = "".join(Path(filename).suffix.lower()[-5:]).lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            ext = ".png"
        await self._remove_photo_file(contact)
        rel = f"{_PHOTO_SUBDIR}/{contact_id}{ext}"
        target = Path(settings.MEDIA_DIR) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        contact.photo_path = rel
        await self.db.commit()
        return await self._reload(contact_id)

    async def delete_photo(self, contact_id: int) -> Contact:
        contact = await self._get(contact_id)
        await self._remove_photo_file(contact)
        contact.photo_path = None
        await self.db.commit()
        return await self._reload(contact_id)

    @staticmethod
    async def _remove_photo_file(contact: Contact) -> None:
        if contact.photo_path:
            old = Path(settings.MEDIA_DIR) / contact.photo_path
            if old.exists():
                try:
                    old.unlink()
                except OSError:
                    logger.warning("Could not remove old contact photo %s", old)

    @staticmethod
    def photo_abs_path(contact: Contact) -> Path | None:
        if contact.photo_path:
            return Path(settings.MEDIA_DIR) / contact.photo_path
        return None

    # ── vCard I/O ──────────────────────────────────────────────────────────

    async def export_vcf(self, ids: list[int] | None = None) -> str:
        stmt = select(Contact).where(Contact.is_deleted == False)  # noqa: E712
        if ids:
            stmt = stmt.where(Contact.id.in_(ids))
        stmt = stmt.order_by(Contact.name, Contact.email)
        contacts = list((await self.db.execute(stmt)).scalars().all())
        return "\r\n".join(serialize_vcard(c) for c in contacts) + "\r\n"

    async def import_vcf(self, text: str) -> int:
        parsed = parse_vcard(text)
        count = 0
        for entry in parsed:
            emails = entry.get("emails", [])
            if not emails:
                continue  # a contact with no email can't be deduped; skip
            primary = str(emails[0]).strip().lower()
            existing = (
                await self.db.execute(select(Contact).where(Contact.email == primary))
            ).scalar_one_or_none()
            phones_typed = entry.get("phones_typed", [])
            if existing is None:
                contact = Contact(
                    email=primary,
                    emails_extra=[str(e) for e in emails[1:]] or None,
                    name=entry.get("name"),
                    nickname=entry.get("nickname"),
                    phones=phones_typed or None,
                    phone=phones_typed[0]["value"] if phones_typed else None,
                    phone_secondary=(
                        phones_typed[1]["value"] if len(phones_typed) > 1 else None
                    ),
                    addresses=entry.get("addresses") or None,
                    websites=entry.get("websites") or None,
                    dates=entry.get("dates") or None,
                    im_handles=entry.get("im") or None,
                    company=entry.get("company"),
                    title=entry.get("title"),
                    notes=entry.get("notes"),
                    source="vcard",
                )
                self.db.add(contact)
                await self.db.flush()
                await self._set_groups_from_names(contact, entry.get("categories", []))
                count += 1
            else:
                # Enrich: never overwrite user data; fill blanks only.
                if not existing.name and entry.get("name"):
                    existing.name = entry.get("name")  # type: ignore[assignment]
                if not existing.company and entry.get("company"):
                    existing.company = entry.get("company")  # type: ignore[assignment]
        await self.db.commit()
        return count

    async def _set_groups_from_names(self, contact: Contact, names: object) -> None:
        """Best-effort: get-or-create groups from vCard CATEGORIES names."""
        if not isinstance(names, list) or not names:
            return
        group_ids: list[int] = []
        for raw in names:
            gname = str(raw).strip()
            if not gname:
                continue
            existing = (
                await self.db.execute(select(ContactGroup).where(ContactGroup.name == gname))
            ).scalar_one_or_none()
            if existing is None:
                existing = ContactGroup(name=gname)
                self.db.add(existing)
                await self.db.flush()
            group_ids.append(existing.id)
        await self._replace_memberships(contact.id, group_ids)

    # ── Auto-extraction (called by email sync) ─────────────────────────────

    async def upsert_from_email(
        self, address: str, display_name: str | None, account_id: int
    ) -> Contact | None:
        """Upsert a contact derived from an email address.

        Dedupe by lowercased primary email. New addresses become source="email".
        Existing contacts only have ``last_seen_at`` refreshed; ``name`` is
        enriched solely for source="email" contacts when empty.
        """
        addr = address.strip().lower()
        if not addr or "@" not in addr:
            return None
        existing = (
            await self.db.execute(select(Contact).where(Contact.email == addr))
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            contact = Contact(
                email=addr,
                name=display_name or None,
                source="email",
                last_seen_at=now,
                email_account_id=account_id,
            )
            self.db.add(contact)
            await self.db.flush()
            return contact
        existing.last_seen_at = now
        if (
            existing.source == "email"
            and display_name
            and not existing.name
        ):
            existing.name = display_name
        await self.db.flush()
        return existing

    # ── helpers ────────────────────────────────────────────────────────────

    async def _assert_unique(self, email: str, exclude_id: int | None = None) -> None:
        stmt = select(Contact.id).where(Contact.email == email)
        if exclude_id is not None:
            stmt = stmt.where(Contact.id != exclude_id)
        if (await self.db.execute(stmt)).scalar_one_or_none() is not None:
            raise ConflictError(f"A contact with email {email} already exists")
