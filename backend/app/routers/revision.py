"""Revision route handlers — entry version history, diff, and restore."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.revision import RevisionDiffResponse, RevisionListResponse, RevisionResponse
from app.services.revision_service import RevisionService

router = APIRouter(prefix="/api/v1/entries/{entry_id}/revisions", tags=["revisions"])


@router.get("", response_model=RevisionListResponse)
async def list_revisions(
    entry_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all revision snapshots for an entry."""
    svc = RevisionService(db)
    items, total = await svc.list_revisions(entry_id, offset, limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/{revision_number}", response_model=RevisionResponse)
async def get_revision(
    entry_id: int, revision_number: int, db: AsyncSession = Depends(get_db)
) -> Any:
    """Get a specific revision snapshot."""
    svc = RevisionService(db)
    return await svc.get_revision(entry_id, revision_number)


@router.get("/{from_rev}/diff/{to_rev}", response_model=RevisionDiffResponse)
async def diff_revisions(
    entry_id: int, from_rev: int, to_rev: int, db: AsyncSession = Depends(get_db)
) -> Any:
    """Compare two revisions of an entry."""
    svc = RevisionService(db)
    return await svc.diff(entry_id, from_rev, to_rev)


@router.post("/{revision_number}/restore", response_model=RevisionResponse)
async def restore_revision(
    entry_id: int, revision_number: int, db: AsyncSession = Depends(get_db)
) -> Any:
    """Restore an entry to a previous revision, creating a pre-restore snapshot."""
    svc = RevisionService(db)
    await svc.restore(entry_id, revision_number)
    # Return the restored revision (same content as current state now)
    return await svc.get_revision(entry_id, revision_number)
