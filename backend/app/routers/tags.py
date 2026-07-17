"""Tag route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.tag import Tag
from app.schemas.tag import TagBrief, TagCreate, TagResponse, TagUpdate
from app.services.tag_service import TagService

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


async def _to_response(tag: Tag, svc: TagService) -> Any:
    """Build a TagResponse from a Tag ORM object."""
    children = [TagBrief(id=c.id, name=c.name) for c in await svc.list_tree(tag.id)]
    entry_count = await svc.get_entry_count(tag.id)
    return TagResponse(
        id=tag.id,
        name=tag.name,
        parent_id=tag.parent_id,
        children=children,
        entry_count=entry_count,
    )


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(data: TagCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a new tag."""
    svc = TagService(db)
    return await _to_response(await svc.create(data), svc)


@router.get("", response_model=list[TagResponse])
async def list_tags(parent_id: int | None = Query(None), db: AsyncSession = Depends(get_db)) -> Any:
    """List tags as a tree or filtered by parent."""
    svc = TagService(db)
    tags = await svc.list_tree(parent_id)
    return [await _to_response(t, svc) for t in tags]


@router.get("/tree", response_model=list[TagResponse])
async def get_tag_tree(db: AsyncSession = Depends(get_db)) -> Any:
    """Get full tag tree (all root tags with children)."""
    svc = TagService(db)
    tags = await svc.list_tree(None)
    return [await _to_response(t, svc) for t in tags]


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a single tag with hierarchy info."""
    svc = TagService(db)
    return await _to_response(await svc.get(tag_id), svc)


@router.patch("/{tag_id}", response_model=TagResponse)
async def rename_tag(tag_id: int, data: TagUpdate, db: AsyncSession = Depends(get_db)) -> Any:
    """Rename a tag."""
    svc = TagService(db)
    return await _to_response(await svc.rename(tag_id, data), svc)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a tag and dissociate from all entries."""
    svc = TagService(db)
    await svc.delete(tag_id)
