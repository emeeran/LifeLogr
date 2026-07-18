"""Contact route handlers — CRUD, groups, vCard import/export, photos, related emails."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.schemas.contact import (
    ContactCreate,
    ContactGroupCreate,
    ContactGroupResponse,
    ContactGroupUpdate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
    RelatedEmailResponse,
)
from app.services.contact_service import ContactService, contact_to_response

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    group_id: int | None = Query(default=None),
    favorites_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List contacts (paginated, optional search / group / favorites filter)."""
    svc = ContactService(db)
    items = await svc.list_all(
        search=search,
        offset=offset,
        limit=limit,
        group_id=group_id,
        favorites_only=favorites_only,
    )
    total = await svc.count(search=search, group_id=group_id, favorites_only=favorites_only)
    return ContactListResponse(
        items=[contact_to_response(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=ContactResponse, status_code=201)
async def create_contact(data: ContactCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a contact manually."""
    svc = ContactService(db)
    return await svc.create(data)


# ── vCard import/export — MUST come before /{contact_id} ────────────────────


@router.get("/export")
async def export_contacts(
    ids: str | None = Query(
        default=None, description="Comma-separated contact IDs (all if omitted)"
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export contacts as a vCard (.vcf) download."""
    svc = ContactService(db)
    id_list: list[int] | None = None
    if ids:
        id_list = []
        for part in ids.split(","):
            part = part.strip()
            if part.isdigit():
                id_list.append(int(part))
    text = await svc.export_vcf(id_list)
    return Response(
        content=text,
        media_type="text/vcard",
        headers={"Content-Disposition": 'attachment; filename="contacts.vcf"'},
    )


@router.post("/import")
async def import_contacts(file: UploadFile, db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Import contacts from an uploaded .vcf file."""
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    svc = ContactService(db)
    count = await svc.import_vcf(text)
    return {"imported": count}


@router.post("/bulk-delete", status_code=204)
async def bulk_delete(ids: list[int], db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete multiple contacts in a single update (idempotent)."""
    svc = ContactService(db)
    await svc.delete_many(ids)


# ── Groups — MUST come before /{contact_id} ─────────────────────────────────


@router.get("/groups", response_model=list[ContactGroupResponse])
async def list_groups(db: AsyncSession = Depends(get_db)) -> Any:
    """List all contact groups with member counts."""
    return await ContactService(db).list_groups()


@router.post("/groups", response_model=ContactGroupResponse, status_code=201)
async def create_group(data: ContactGroupCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a contact group."""
    return await ContactService(db).create_group(data)


@router.patch("/groups/{group_id}", response_model=ContactGroupResponse)
async def update_group(
    group_id: int, data: ContactGroupUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Rename / recolour a contact group."""
    return await ContactService(db).update_group(group_id, data)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a contact group (members are unlinked, not deleted)."""
    await ContactService(db).delete_group(group_id)


# ── Per-contact CRUD ───────────────────────────────────────────────────────


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a specific contact."""
    svc = ContactService(db)
    return contact_to_response(await svc.get(contact_id))


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int, data: ContactUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Update a contact."""
    svc = ContactService(db)
    return contact_to_response(await svc.update(contact_id, data))


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete a contact."""
    svc = ContactService(db)
    await svc.delete(contact_id)


@router.post("/{contact_id}/restore", response_model=ContactResponse)
async def restore_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Restore a soft-deleted contact."""
    svc = ContactService(db)
    return contact_to_response(await svc.restore(contact_id))


# ── Photo + related emails ─────────────────────────────────────────────────


@router.get("/{contact_id}/photo")
async def get_contact_photo(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Serve a contact's photo (404 if none)."""
    svc = ContactService(db)
    contact = await svc.get(contact_id)
    path = svc.photo_abs_path(contact)
    if path is None or not path.exists():
        raise NotFoundError(f"Contact {contact_id} has no photo")
    return FileResponse(path=str(path))


@router.post("/{contact_id}/photo", response_model=ContactResponse)
async def upload_contact_photo(
    contact_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload/replace a contact's photo."""
    svc = ContactService(db)
    data = await file.read()
    return contact_to_response(await svc.set_photo(contact_id, data, file.filename or "photo.png"))


@router.delete("/{contact_id}/photo", response_model=ContactResponse)
async def delete_contact_photo(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Remove a contact's photo."""
    svc = ContactService(db)
    return contact_to_response(await svc.delete_photo(contact_id))


@router.get("/{contact_id}/emails", response_model=list[RelatedEmailResponse])
async def related_emails(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Emails involving this contact's address(es) — the EPIM 'related emails' view."""
    svc = ContactService(db)
    return await svc.related_emails(contact_id)
