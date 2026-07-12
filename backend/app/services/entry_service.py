"""Business logic for journal entries."""

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.sql.expression import Select as Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.entry import Entry
from app.models.tag import EntryTag, Tag
from app.schemas.entry import CalendarEntryResponse, EntryCreate, EntryUpdate
from app.schemas.tag import TagBrief
from app.services.enrichment_service import EnrichmentService

logger = logging.getLogger(__name__)


class EntryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: EntryCreate) -> Entry:
        """Create a new journal entry."""
        entry = Entry(
            entry_date=data.entry_date,
            title=data.title,
            body=data.body,
            mood=data.mood,
            template_id=data.template_id,
        )
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
        template_id: int | None = None,
    ) -> tuple[list[Entry], int]:
        """Return paginated entries matching optional filters and total count."""
        base_q = select(Entry).where(Entry.is_deleted.is_(False))
        base_q = self._apply_filters(base_q, tag_ids, mood, year, month, template_id)
        count_q = self._apply_filters(
            select(func.count()).select_from(Entry).where(Entry.is_deleted.is_(False)),
            tag_ids,
            mood,
            year,
            month,
            template_id,
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
                    delete(EntryTag).where(EntryTag.entry_id == entry_id, EntryTag.tag_id.in_(to_remove))
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

        media_result = await self.db.execute(select(Media).where(Media.entry_id == entry_id))
        media_list = media_result.scalars().all()
        if media_list:
            for media in media_list:
                full_path = settings.MEDIA_DIR / media.storage_path
                if full_path.exists():
                    full_path.unlink()
                await self.db.delete(media)

        await self.db.commit()
        # Best-effort: drop from the vector cache now (ensure_fresh reloads on
        # any divergence anyway, so a miss here self-heals on the next search).
        try:
            from app.services.semantic_cache import get_semantic_cache

            get_semantic_cache().remove_entry(entry_id)
        except Exception:
            logger.warning("Failed to drop entry %d from semantic cache", entry_id, exc_info=True)

    async def restore(self, entry_id: int) -> Entry:
        """Un-delete a soft-deleted entry.

        The FTS ``fts_entry_restore`` trigger re-indexes the entry automatically.
        Note: media files removed at soft-delete time are not restored (they
        were permanently deleted); the entry's text content is fully recovered.
        """
        # Fetch even if soft-deleted by querying without the default filter.
        result = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        entry = result.scalar_one_or_none()
        if entry is None:
            raise NotFoundError(f"Entry {entry_id} not found")
        if not entry.is_deleted:
            return entry  # already live — idempotent
        entry.is_deleted = False
        entry.deleted_at = None
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

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

    async def get_calendar_month_light(self, year: int, month: int) -> list[CalendarEntryResponse]:
        """Return lightweight entry projections for a calendar grid.

        Unlike ``get_calendar_month``, this **excludes the body** (which can
        be kilobytes per entry) and loads only the fields the grid needs:
        id, entry_date, title, mood, and tags (batched in a second query to
        avoid N+1). For a month with many long entries this dramatically
        reduces JSON payload and parse time.
        """
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        entries_result = await self.db.execute(
            select(Entry.id, Entry.entry_date, Entry.title, Entry.mood, Entry.is_encrypted)
            .where(Entry.is_deleted == False, Entry.entry_date >= start, Entry.entry_date < end)  # noqa: E712
            .order_by(Entry.entry_date)
        )
        rows = entries_result.all()
        if not rows:
            return []

        entry_ids = [r.id for r in rows]
        tags_result = await self.db.execute(
            select(EntryTag.entry_id, Tag.id, Tag.name)
            .join(Tag, EntryTag.tag_id == Tag.id)
            .where(EntryTag.entry_id.in_(entry_ids))
        )
        tags_map: dict[int, list[TagBrief]] = {}
        for tr in tags_result.all():
            tags_map.setdefault(tr.entry_id, []).append(TagBrief(id=tr.id, name=tr.name))

        return [
            CalendarEntryResponse(
                id=r.id,
                entry_date=r.entry_date,
                title=r.title,
                mood=r.mood,
                is_encrypted=r.is_encrypted,
                tags=tags_map.get(r.id, []),
            )
            for r in rows
        ]

    async def search(self, query: str, offset: int, limit: int) -> tuple[list[Entry], int]:
        """Full-text search via FTS5 index (falls back to ILIKE on error).

        FTS5 uses the dedicated ``entries_fts`` virtual table maintained by
        triggers, so this is index-backed and sargable — unlike the previous
        ``ILIKE '%..%'`` which forced a full table scan.
        """
        from sqlalchemy import text as sa_text

        # Sanitise the query for FTS5 MATCH: quote each token so special
        # characters / operators don't break the parser.
        fts_query = " ".join(f'"{tok}"' for tok in query.split() if tok.strip())

        try:
            fts_sql = sa_text(
                """
                SELECT e.id FROM entries_fts fts
                JOIN entries e ON e.id = fts.rowid
                WHERE entries_fts MATCH :q AND e.is_deleted = 0
                ORDER BY bm25(entries_fts)
                LIMIT :lim OFFSET :off
                """
            )
            rows = (
                await self.db.execute(fts_sql, {"q": fts_query, "lim": limit, "off": offset})
            ).fetchall()
            entry_ids = [r[0] for r in rows]
            if entry_ids:
                count_sql = sa_text(
                    "SELECT COUNT(*) FROM entries_fts fts JOIN entries e ON e.id = fts.rowid "
                    "WHERE entries_fts MATCH :q AND e.is_deleted = 0"
                )
                total = (await self.db.execute(count_sql, {"q": fts_query})).scalar_one()
                result = await self.db.execute(
                    select(Entry).where(Entry.id.in_(entry_ids))
                )
                # Preserve FTS order
                entry_map = {e.id: e for e in result.scalars().all()}
                return [entry_map[eid] for eid in entry_ids if eid in entry_map], total
            # FTS returned 0 rows — fall through to ILIKE fallback (handles
            # the case where FTS triggers aren't installed, e.g. test DB).
        except Exception:
            logger.warning("FTS search failed, falling back to ILIKE", exc_info=True)

        # FTS unavailable — ILIKE fallback (rare; e.g. corrupt index)
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
        template_id: int | None = None,
    ) -> Select[Any]:
        """Apply common filters to an entry query.

        Date filters use **sargable** range bounds (``>= date(...) AND
        < date(...+1)``) so SQLite can use ``ix_entries_deleted_date``.
        The previous ``strftime('%Y', entry_date)`` formulation wrapped the
        column in a function, defeating the index and forcing a full scan.
        When only ``month`` is given (no year) — a rare any-year query —
        we fall back to ``strftime`` since a range is impossible without a year.
        """
        if tag_ids:
            q = q.join(EntryTag).where(EntryTag.tag_id.in_(tag_ids))
        if mood:
            q = q.where(Entry.mood == mood)
        if template_id is not None:
            q = q.where(Entry.template_id == template_id)
        if year and month:
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            q = q.where(Entry.entry_date >= start, Entry.entry_date < end)
        elif year:
            q = q.where(
                Entry.entry_date >= date(year, 1, 1),
                Entry.entry_date < date(year + 1, 1, 1),
            )
        elif month:
            # Month-only (any year) — rare; strftime is the only option.
            q = q.where(func.strftime("%m", Entry.entry_date) == str(month).zfill(2))
        return q
