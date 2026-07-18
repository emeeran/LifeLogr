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
    """Build a TagResponse from a single Tag ORM object.

    Used by the single-tag endpoints (create/get/rename) where the extra
    child + count queries (2 total) are negligible. The list endpoints use
    ``_build_tree_responses`` instead to avoid an N+1.
    """
    children = [TagBrief(id=c.id, name=c.name) for c in await svc.list_tree(tag.id)]
    entry_count = await svc.get_entry_count(tag.id)
    return TagResponse(
        id=tag.id,
        name=tag.name,
        parent_id=tag.parent_id,
        children=children,
        entry_count=entry_count,
    )


def _build_tree_responses(
    all_tags: list[Tag], roots_parent: int | None, counts: dict[int, int]
) -> list[TagResponse]:
    """Build a list of TagResponse from preloaded data — O(1) queries.

    ``all_tags`` supplies both the roots (those whose ``parent_id`` matches
    ``roots_parent``) and, via an in-memory group-by-parent, every root's
    children. ``counts`` supplies entry counts. This replaces the old
    per-tag ``list_tree`` + ``get_entry_count`` loop (``1 + 2N`` queries)
    with a constant 2 queries regardless of tag count.
    """
    children_by_parent: dict[int | None, list[TagBrief]] = {}
    for t in all_tags:
        children_by_parent.setdefault(t.parent_id, []).append(TagBrief(id=t.id, name=t.name))
    # Roots are full Tag rows (need parent_id/name for the response); children
    # are TagBrief. all_tags is name-ordered, so both roots and each child list
    # stay name-ordered — matching the old per-tag list_tree ordering.
    roots = [t for t in all_tags if t.parent_id == roots_parent]
    return [
        TagResponse(
            id=t.id,
            name=t.name,
            parent_id=t.parent_id,
            children=children_by_parent.get(t.id, []),
            entry_count=counts.get(t.id, 0),
        )
        for t in roots
    ]


async def _list_tree(svc: TagService, parent_id: int | None) -> list[TagResponse]:
    """List tags under ``parent_id`` as responses, in 2 queries total."""
    all_tags = await svc.list_all_ordered()
    counts = await svc.bulk_entry_counts()
    return _build_tree_responses(all_tags, parent_id, counts)


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(data: TagCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create a new tag."""
    svc = TagService(db)
    return await _to_response(await svc.create(data), svc)


@router.get("", response_model=list[TagResponse])
async def list_tags(parent_id: int | None = Query(None), db: AsyncSession = Depends(get_db)) -> Any:
    """List tags as a tree or filtered by parent."""
    svc = TagService(db)
    return await _list_tree(svc, parent_id)


@router.get("/tree", response_model=list[TagResponse])
async def get_tag_tree(db: AsyncSession = Depends(get_db)) -> Any:
    """Get full tag tree (all root tags with children)."""
    svc = TagService(db)
    return await _list_tree(svc, None)


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
