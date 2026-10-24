"""Business logic for tags."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.tag import EntryTag, Tag
from app.schemas.tag import TagCreate, TagUpdate


class TagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: TagCreate) -> Tag:
        """Create a tag; reject duplicate names (case-insensitive)."""
        tag = Tag(name=data.name, parent_id=data.parent_id)
        self.db.add(tag)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(f"Tag '{data.name}' already exists")
        await self.db.commit()
        await self.db.refresh(tag)
        return tag

    async def get(self, tag_id: int) -> Tag:
        """Return a single tag with children and entry count."""
        result = await self.db.execute(select(Tag).where(Tag.id == tag_id))
        tag = result.scalar_one_or_none()
        if not tag:
            raise NotFoundError(f"Tag {tag_id} not found")
        return tag

    async def list_tree(self, parent_id: int | None = None) -> list[Tag]:
        """Return tag hierarchy; full tree or children of a parent."""
        result = await self.db.execute(
            select(Tag).where(Tag.parent_id == parent_id).order_by(Tag.name)
        )
        return list(result.scalars().all())

    async def children_by_parent(self, parent_ids: list[int]) -> dict[int, list[Tag]]:
        """Direct children of each given tag, in one grouped query, name-ordered.

        Batch counterpart of ``list_tree(tag_id)`` so listing N tags costs one
        query instead of N.
        """
        if not parent_ids:
            return {}
        rows = await self.db.execute(
            select(Tag.parent_id, Tag)
            .where(Tag.parent_id.in_(parent_ids))
            .order_by(Tag.name)
        )
        children: dict[int, list[Tag]] = {pid: [] for pid in parent_ids}
        for parent_id, tag in rows.all():
            children[int(parent_id)].append(tag)
        return children

    async def entry_counts(self, tag_ids: list[int]) -> dict[int, int]:
        """Non-deleted entry count per given tag, in one GROUP BY query.

        Batch counterpart of ``get_entry_count``; tags with no entries map to 0.
        """
        from app.models.entry import Entry

        if not tag_ids:
            return {}
        rows = await self.db.execute(
            select(EntryTag.tag_id, func.count())
            .join(Entry, Entry.id == EntryTag.entry_id)
            .where(EntryTag.tag_id.in_(tag_ids), Entry.is_deleted == False)  # noqa: E712
            .group_by(EntryTag.tag_id)
        )
        counts = {int(tag_id): int(n) for tag_id, n in rows.all()}
        return {tid: counts.get(tid, 0) for tid in tag_ids}

    async def rename(self, tag_id: int, data: TagUpdate) -> Tag:
        """Rename a tag; reject duplicate names."""
        tag = await self.get(tag_id)
        tag.name = data.name
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(f"Tag '{data.name}' already exists")
        await self.db.commit()
        await self.db.refresh(tag)
        return tag

    async def delete(self, tag_id: int) -> None:
        """Delete tag and remove all entry associations."""
        tag = await self.get(tag_id)
        await self.db.delete(tag)
        await self.db.commit()

    async def get_entry_count(self, tag_id: int) -> int:
        """Return count of non-deleted entries associated with a tag."""
        from app.models.entry import Entry

        result = await self.db.execute(
            select(func.count())
            .select_from(EntryTag)
            .join(Entry, Entry.id == EntryTag.entry_id)
            .where(EntryTag.tag_id == tag_id, Entry.is_deleted == False)  # noqa: E712
        )
        return result.scalar_one()
