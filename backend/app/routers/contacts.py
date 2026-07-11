"""Contact route handlers — CRUD, vCard import/export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.contact import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from app.services.contact_service import ContactService

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List contacts (paginated, optional search)."""
    svc = ContactService(db)
    items = await svc.list_all(search=search, offset=offset, limit=limit)
    total = await svc.count(search=search)
    return ContactListResponse(
        items=[ContactResponse.model_validate(c) for c in items],
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
async def import_contacts(
    file: UploadFile, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    """Import contacts from an uploaded .vcf file."""
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    svc = ContactService(db)
    count = await svc.import_vcf(text)
    return {"imported": count}


@router.post("/bulk-delete", status_code=204)
async def bulk_delete(ids: list[int], db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete multiple contacts."""
    svc = ContactService(db)
    for contact_id in ids:
        await svc.delete(contact_id)


# ── Per-contact CRUD ───────────────────────────────────────────────────────


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a specific contact."""
    svc = ContactService(db)
    return await svc.get(contact_id)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int, data: ContactUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Update a contact."""
    svc = ContactService(db)
    return await svc.update(contact_id, data)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Soft-delete a contact."""
    svc = ContactService(db)
    await svc.delete(contact_id)


@router.post("/{contact_id}/restore", response_model=ContactResponse)
async def restore_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Restore a soft-deleted contact."""
    svc = ContactService(db)
    return await svc.restore(contact_id)
