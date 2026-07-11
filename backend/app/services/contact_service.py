"""ContactService — CRUD, vCard import/export, and email auto-extraction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate, _normalize_email

logger = logging.getLogger(__name__)


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


def _split_property(line: str) -> tuple[str, str]:
    """Split a vCard property line into (NAME, value), stripping params."""
    # Property form: NAME;PARAM=...;PARAM=...:VALUE — the first ':' separates
    # name+params from value. Values may legally contain ':' (e.g. URLs).
    if ":" not in line:
        return "", ""
    head, value = line.split(":", 1)
    name = head.split(";", 1)[0].upper()
    return name, value


def parse_vcard(text: str) -> list[dict[str, object]]:
    """Parse vCard text into a list of contact dicts.

    Each dict has keys: name, emails (list[str]), phones (list[str]),
    company, title, notes. Only vCard 3.0 fields we model are extracted.
    """
    contacts: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in _unfold(text):
        name, value = _split_property(line)
        if name == "BEGIN" and value.upper() == "VCARD":
            current = {"emails": [], "phones": []}
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
        elif name == "EMAIL":
            addr = value.strip().lower()
            if addr and addr not in current["emails"]:
                current["emails"].append(addr)
        elif name == "TEL":
            if value.strip():
                current["phones"].append(value.strip())
        elif name == "ORG":
            current["company"] = value.split(";", 1)[0]
        elif name == "TITLE":
            current["title"] = value
        elif name == "NOTE":
            current["notes"] = value
    return contacts


def _fold_line(line: str, width: int = 75) -> str:
    """Fold a single property line to the RFC 5545 octet width."""
    if len(line.encode("utf-8")) <= width:
        return line
    out: list[str] = []
    # Fold by characters, respecting byte width (UTF-8 safe enough for v1).
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


def serialize_vcard(c: Contact) -> str:
    """Serialize a single contact to a vCard 3.0 block."""
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    fn = c.name or c.email
    lines.append(f"FN:{fn}")
    # N: best-effort split of name into family/given.
    if c.name:
        parts = c.name.rsplit(" ", 1)
        family = parts[-1] if len(parts) > 1 else c.name
        given = parts[0] if len(parts) > 1 else ""
        lines.append(f"N:{family};{given};;;")
    lines.append(f"EMAIL;TYPE=internet:{c.email}")
    for extra in c.emails_extra or []:
        lines.append(f"EMAIL;TYPE=internet:{extra}")
    if c.phone:
        lines.append(f"TEL;TYPE=cell:{c.phone}")
    if c.phone_secondary:
        lines.append(f"TEL;TYPE=home:{c.phone_secondary}")
    if c.company:
        lines.append(f"ORG:{c.company}")
    if c.title:
        lines.append(f"TITLE:{c.title}")
    if c.notes:
        note_val = c.notes.replace("\n", "\\n")
        lines.append(f"NOTE:{note_val}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold_line(ln) for ln in lines)


# ── Service ────────────────────────────────────────────────────────────────


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
            notes=data.notes,
            source="manual",
        )
        self.db.add(contact)
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def get(self, contact_id: int) -> Contact:
        return await self._get(contact_id)

    async def list_all(
        self, search: str | None = None, offset: int = 0, limit: int = 100
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
        stmt = stmt.order_by(Contact.name, Contact.email).offset(offset).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def count(self, search: str | None = None) -> int:
        """Total non-deleted contacts matching the optional search filter."""
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
        if data.phone is not None:
            contact.phone = data.phone
        if data.phone_secondary is not None:
            contact.phone_secondary = data.phone_secondary
        if data.company is not None:
            contact.company = data.company
        if data.title is not None:
            contact.title = data.title
        if data.notes is not None:
            contact.notes = data.notes
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

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
        await self.db.refresh(contact)
        return contact

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
            phones = entry.get("phones", [])
            if existing is None:
                self.db.add(
                    Contact(
                        email=primary,
                        emails_extra=[str(e) for e in emails[1:]] or None,
                        name=entry.get("name"),
                        phone=phones[0] if phones else None,
                        phone_secondary=phones[1] if len(phones) > 1 else None,
                        company=entry.get("company"),
                        title=entry.get("title"),
                        notes=entry.get("notes"),
                        source="vcard",
                    )
                )
                count += 1
            else:
                # Enrich: never overwrite user data; fill blanks only.
                if not existing.name and entry.get("name"):
                    existing.name = entry.get("name")  # type: ignore[assignment]
                if not existing.company and entry.get("company"):
                    existing.company = entry.get("company")  # type: ignore[assignment]
        await self.db.commit()
        return count

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
