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

    async def associate(self, entry_id: int, tag_ids: list[int]) -> None:
        """Associate tags with an entry; skip already-associated."""
        for tag_id in tag_ids:
            existing = await self.db.execute(
                select(EntryTag).where(EntryTag.entry_id == entry_id, EntryTag.tag_id == tag_id)
            )
            if not existing.scalar_one_or_none():
                self.db.add(EntryTag(entry_id=entry_id, tag_id=tag_id))
        await self.db.flush()

    async def dissociate(self, entry_id: int, tag_ids: list[int]) -> None:
        """Remove tag associations from an entry."""
        for tag_id in tag_ids:
            result = await self.db.execute(
                select(EntryTag).where(EntryTag.entry_id == entry_id, EntryTag.tag_id == tag_id)
            )
            if assoc := result.scalar_one_or_none():
                await self.db.delete(assoc)
        await self.db.flush()

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
