"""Business logic for journal entries."""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.sql.expression import Select as Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.entry import Entry
from app.models.tag import EntryTag
from app.schemas.entry import EntryCreate, EntryUpdate
from app.services.enrichment_service import EnrichmentService


class EntryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: EntryCreate) -> Entry:
        """Create a new journal entry."""
        entry = Entry(entry_date=data.entry_date, title=data.title, body=data.body, mood=data.mood)
        self.db.add(entry)
        await self.db.flush()
        if data.tag_ids:
            self.db.add_all([EntryTag(entry_id=entry.id, tag_id=tid) for tid in data.tag_ids])
            await self.db.flush()
        await self.db.commit()
        await self.db.refresh(entry)
        EnrichmentService.schedule(entry.id, entry.title, entry.body)
        return entry

    async def get(self, entry_id: int) -> Entry:
        """Return a single non-deleted entry by ID."""
        result = await self.db.execute(
            select(Entry).where(Entry.id == entry_id, Entry.is_deleted == False)  # noqa: E712
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found")
        return entry

    async def list_entries(
        self,
        offset: int,
        limit: int,
        tag_ids: list[int] | None = None,
        mood: str | None = None,
        year: int | None = None,
        month: int | None = None,
    ) -> tuple[list[Entry], int]:
        """Return paginated entries matching optional filters and total count."""
        base_q = select(Entry).where(Entry.is_deleted.is_(False))
        base_q = self._apply_filters(base_q, tag_ids, mood, year, month)
        count_q = self._apply_filters(
            select(func.count()).select_from(Entry).where(Entry.is_deleted.is_(False)),
            tag_ids,
            mood,
            year,
            month,
        )
        total = (await self.db.execute(count_q)).scalar_one()
        result = await self.db.execute(
            base_q.order_by(Entry.entry_date.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def update(self, entry_id: int, data: EntryUpdate) -> Entry:
        """Update body, mood, and/or tags of an existing entry."""
        entry = await self.get(entry_id)
        if data.body is not None:
            entry.body = data.body
        if data.title is not None:
            entry.title = data.title
        if data.mood is not None:
            entry.mood = data.mood
        if data.tag_ids is not None:
            current = {a.tag_id for a in entry.tag_associations}
            desired = set(data.tag_ids)
            to_add = desired - current
            to_remove = current - desired
            if to_add:
                self.db.add_all([EntryTag(entry_id=entry_id, tag_id=tid) for tid in to_add])
            if to_remove:
                await self.db.execute(
                    EntryTag.__table__.delete().where(
                        EntryTag.entry_id == entry_id, EntryTag.tag_id.in_(to_remove)  # type: ignore[attr-defined]
                    )
                )
        await self.db.commit()
        await self.db.refresh(entry)
        EnrichmentService.schedule(entry.id, entry.title, entry.body)
        return entry

    async def soft_delete(self, entry_id: int) -> None:
        """Mark entry as deleted; remove associated media files."""
        entry = await self.get(entry_id)
        entry.is_deleted = True
        entry.deleted_at = datetime.now(timezone.utc)

        # Clean up media files for the soft-deleted entry
        from app.models.media import Media
        from app.services.media_service import MediaService

        media_result = await self.db.execute(select(Media).where(Media.entry_id == entry_id))
        media_list = media_result.scalars().all()
        if media_list:
            media_svc = MediaService(self.db)
            for media in media_list:
                await media_svc.delete(media.id)

        await self.db.commit()

    async def get_calendar_month(self, year: int, month: int) -> list[Entry]:
        """Return all non-deleted entries for a given month."""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        result = await self.db.execute(
            select(Entry)
            .where(Entry.is_deleted == False, Entry.entry_date >= start, Entry.entry_date < end)  # noqa: E712
            .order_by(Entry.entry_date)
        )
        return list(result.scalars().all())

    async def search(self, query: str, offset: int, limit: int) -> tuple[list[Entry], int]:
        """Full-text search on entry body; return matches and total count."""
        pattern = f"%{query}%"
        base = select(Entry).where(
            Entry.is_deleted == False,  # noqa: E712
            (Entry.body.ilike(pattern)) | (Entry.title.ilike(pattern)),
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        result = await self.db.execute(
            base.order_by(Entry.entry_date.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    @staticmethod
    def _apply_filters(
        q: Select[Any],
        tag_ids: list[int] | None,
        mood: str | None,
        year: int | None,
        month: int | None,
    ) -> Select[Any]:
        """Apply common filters to an entry query."""
        if tag_ids:
            q = q.join(EntryTag).where(EntryTag.tag_id.in_(tag_ids))
        if mood:
            q = q.where(Entry.mood == mood)
        if year:
            q = q.where(func.strftime("%Y", Entry.entry_date) == str(year))
        if month:
            q = q.where(func.strftime("%m", Entry.entry_date) == str(month).zfill(2))
        return q
