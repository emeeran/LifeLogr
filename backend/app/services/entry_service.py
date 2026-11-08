"""Business logic for journal entries."""

import logging
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Connection, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy.sql.expression import Select as Select

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.entry import Entry
from app.models.media import Media
from app.models.tag import EntryTag, Tag
from app.schemas.entry import (
    CalendarEntryResponse,
    EntryCreate,
    EntryUpdate,
    JournalStatsResponse,
    MediaTypeCount,
    MoodCount,
    WeeklyCount,
)
from app.schemas.tag import TagBrief
from app.services.enrichment_service import EnrichmentService
from app.services.weather_service import WeatherService
from app.services.hashtag import extract_hashtags, resolve_tag_ids

logger = logging.getLogger(__name__)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _word_count(text: str | None) -> int:
    """Whitespace-run word count — the one definition of "word" for the app.

    Matches the frontend helper in ``frontend/src/utils/text.ts`` (trim, split
    on whitespace runs). Used by the calendar projection so the daily
    word-count goal can total a day's entries without shipping bodies to the
    client, and by the stats aggregates.
    """
    if not text:
        return 0
    return len(text.split())


def _current_streak(dates: list[date], today: date) -> int:
    """Consecutive days with an entry ending today (or yesterday — a streak
    isn't broken just because today's entry hasn't been written yet)."""
    dayset = set(dates)
    streak = 0
    d = today if today in dayset else today - timedelta(days=1)
    while d in dayset:
        streak += 1
        d -= timedelta(days=1)
    return streak


def _longest_streak(dates: list[date]) -> int:
    """Longest run of consecutive entry days across all history."""
    longest = current = 0
    prev: date | None = None
    for d in dates:  # sorted ascending
        current = current + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, current)
        prev = d
    return longest


def _entry_list_options() -> tuple[Any, ...]:
    """Eager-load relationships + every scalar column EXCEPT the heavy ``body``.

    Built lazily (called per-query, not at module import) so it doesn't trigger
    SQLAlchemy mapper configuration before all models are registered.
    """
    return (
        load_only(
            Entry.id,
            Entry.entry_date,
            Entry.title,
            Entry.summary,
            Entry.mood,
            Entry.is_deleted,
            Entry.is_encrypted,
            Entry.latitude,
            Entry.longitude,
            Entry.location_name,
            Entry.template_id,
            Entry.created_at,
            Entry.updated_at,
        ),
        selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
        selectinload(Entry.media),
        selectinload(Entry.recordings),
    )


# In-memory cache for the stats aggregates (keyed by database URL — the app
# has one DB, the tests many). Every entry mutation calls
# :func:`invalidate_stats_cache`, so the TTL only bounds staleness from
# out-of-band writes (e.g. direct imports in other processes).
_STATS_CACHE_TTL = 60.0
_stats_cache: dict[str, tuple[float, JournalStatsResponse]] = {}


def invalidate_stats_cache() -> None:
    """Drop the cached stats aggregates (call after any entry/media mutation)."""
    _stats_cache.clear()


async def get_entry_or_raise(
    db: AsyncSession, entry_id: int, *, include_deleted: bool = False
) -> Entry:
    """Return the entry by ID, raising :class:`NotFoundError` if it doesn't
    exist — or is soft-deleted, unless ``include_deleted`` (some paths, like
    attachment serving, stay valid for deleted entries)."""
    stmt = select(Entry).where(Entry.id == entry_id)
    if not include_deleted:
        stmt = stmt.where(Entry.is_deleted == False)  # noqa: E712
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise NotFoundError(f"Entry {entry_id} not found")
    return entry


class EntryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: EntryCreate, *, commit: bool = True) -> Entry:
        """Create a new journal entry.

        ``commit=False`` defers the commit *and* the enrichment scheduling to
        the caller: the bulk importers use it to write a whole batch in one
        transaction instead of paying a commit (an fsync) per row. Rows written
        this way are invisible to other sessions — including the background
        enrichment workers, which open their own session — until the caller
        commits, so the caller MUST commit before scheduling enrichment
        (``EnrichmentService.schedule``) for the returned ids.
        """
        if not commit:
            return await self._create_batched(data)

        entry = Entry(
            entry_date=data.entry_date,
            title=data.title,
            body=data.body,
            mood=data.mood,
            latitude=data.latitude,
            longitude=data.longitude,
            template_id=data.template_id,
        )
        self.db.add(entry)
        await self.db.flush()
        # Tags come from two sources: #hashtags in the body AND the explicit
        # ``tag_ids`` list (the editor's tag picker and the importers both send
        # it — it was silently dropped before, losing imported tags).
        desired = await self._desired_tag_ids(data.body, data.tag_ids or [])
        if desired:
            self.db.add_all([EntryTag(entry_id=entry.id, tag_id=tid) for tid in desired])
            await self.db.flush()
        await self.db.commit()
        await self.db.refresh(entry)
        invalidate_stats_cache()
        # Never enrich encrypted entries — their body column holds ciphertext,
        # which must not be sent to the LLM or indexed.
        if not entry.is_encrypted:
            EnrichmentService.schedule(entry.id, entry.title, entry.body)
            WeatherService.schedule(entry.id, entry.latitude, entry.longitude, entry.entry_date)
        return entry

    async def _create_batched(self, data: EntryCreate) -> Entry:
        """Insert one entry inside a SAVEPOINT, leaving the commit to the caller.

        The savepoint isolates each imported row: a bad record (bad date, body
        over the column limit, …) rolls back only itself, so the rest of the
        in-flight batch survives and the per-row skip accounting stays exactly
        what the single-row-commit version produced.
        """
        async with self.db.begin_nested():
            entry = Entry(
                entry_date=data.entry_date,
                title=data.title,
                body=data.body,
                mood=data.mood,
                latitude=data.latitude,
                longitude=data.longitude,
                template_id=data.template_id,
            )
            self.db.add(entry)
            await self.db.flush()
            desired = await self._desired_tag_ids(data.body, data.tag_ids or [])
            if desired:
                self.db.add_all([EntryTag(entry_id=entry.id, tag_id=tid) for tid in desired])
        invalidate_stats_cache()
        return entry

    async def _desired_tag_ids(self, body: str | None, explicit_tag_ids: list[int]) -> set[int]:
        """Union of the body's #hashtags (resolved/created) and explicit tag ids."""
        desired: set[int] = set(explicit_tag_ids)
        names = extract_hashtags(body)
        if names:
            desired.update(await resolve_tag_ids(self.db, names))
        return desired

    async def get(self, entry_id: int) -> Entry:
        """Return a single non-deleted entry by ID."""
        return await get_entry_or_raise(self.db, entry_id)

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
        base_q = select(Entry).options(*_entry_list_options()).where(Entry.is_deleted.is_(False))
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

    async def body_snippets(self, entry_ids: list[int]) -> dict[int, str]:
        """Server-side ~300-char body snippets for the given entries.

        Skips encrypted entries (their body is ciphertext → empty snippet; the UI
        shows 'Encrypted'). Avoids materializing full bodies into memory.
        """
        if not entry_ids:
            return {}
        rows = await self.db.execute(
            select(Entry.id, func.substr(Entry.body, 1, 300)).where(
                Entry.id.in_(entry_ids),
                Entry.is_encrypted == False,  # noqa: E712
            )
        )
        return {row[0]: (row[1] or "") for row in rows.all()}

    async def update(self, entry_id: int, data: EntryUpdate) -> Entry:
        """Update body, mood, tags, and/or location of an existing entry."""
        entry = await self.get(entry_id)
        if data.body is not None:
            entry.body = data.body
        if data.title is not None:
            entry.title = data.title
        if "mood" in data.model_fields_set:
            entry.mood = data.mood
        if data.latitude is not None:
            entry.latitude = data.latitude
        if data.longitude is not None:
            entry.longitude = data.longitude
        # Tag sources: #hashtags in the body (re-derived whenever the body
        # changes — the body stays the source of truth) plus the explicit
        # ``tag_ids`` list sent by the editor/importers (previously ignored).
        desired: set[int] | None = None
        if data.body is not None:
            desired = await self._desired_tag_ids(data.body, data.tag_ids or [])
        elif data.tag_ids is not None:
            desired = set(data.tag_ids)
        if desired is not None:
            current = {a.tag_id for a in entry.tag_associations}
            to_add = desired - current
            to_remove = current - desired
            if to_add:
                self.db.add_all([EntryTag(entry_id=entry_id, tag_id=tid) for tid in to_add])
            if to_remove:
                await self.db.execute(
                    delete(EntryTag).where(
                        EntryTag.entry_id == entry_id, EntryTag.tag_id.in_(to_remove)
                    )
                )
        await self.db.commit()
        await self.db.refresh(entry)
        invalidate_stats_cache()
        # Never enrich encrypted entries — their body column holds ciphertext,
        # which must not be sent to the LLM or indexed.
        if not entry.is_encrypted:
            EnrichmentService.schedule(entry.id, entry.title, entry.body)
            WeatherService.schedule(entry.id, entry.latitude, entry.longitude, entry.entry_date)
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
        for media in media_list:
            await self.db.delete(media)

        # Commit BEFORE unlinking files: if the commit failed after the files
        # were gone, the DB would reference media that no longer exists (and
        # restore() could never bring them back). A failed unlink after a
        # successful commit only orphans a file, which is recoverable.
        await self.db.commit()
        for media in media_list:
            full_path = settings.MEDIA_DIR / media.storage_path
            if full_path.exists():
                try:
                    full_path.unlink()
                except OSError:
                    logger.warning(
                        "Could not remove media file %s for soft-deleted entry %s",
                        full_path,
                        entry_id,
                        exc_info=True,
                    )
        invalidate_stats_cache()
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
        invalidate_stats_cache()
        return entry

    async def get_calendar_month_light(self, year: int, month: int) -> list[CalendarEntryResponse]:
        """Return lightweight entry projections for a calendar grid.

        Unlike a full-body month query, this **excludes the body from the
        response** (which can be kilobytes per entry) and loads only the
        fields the grid needs: id, entry_date, title, mood, tags (batched in
        a second query to avoid N+1), and a server-side ``word_count`` for
        the daily goal. For a month with many long entries this dramatically
        reduces JSON payload and parse time.
        """
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        entries_result = await self.db.execute(
            select(
                Entry.id,
                Entry.entry_date,
                Entry.title,
                Entry.mood,
                Entry.is_encrypted,
                Entry.body,
            )
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
                # Bodies are loaded server-side but never sent — only the count
                # is; encrypted bodies are ciphertext, so count 0.
                word_count=0 if r.is_encrypted else _word_count(r.body),
                tags=tags_map.get(r.id, []),
            )
            for r in rows
        ]

    async def get_stats(self, weeks: int = 12) -> JournalStatsResponse:
        """Journal aggregates for the stats dashboard, cached in memory.

        One query pass per component (dates, bodies, moods, media). Total
        words reuses :func:`_word_count` so it matches the daily goal and the
        calendar's counts; bodies are read but never leave the server.
        """
        bind = self.db.get_bind()
        # A Connection exposes .engine; an Engine is already what we want. The
        # getattr dance is untyped — narrow explicitly for mypy and readers.
        engine = bind.engine if isinstance(bind, Connection) else bind
        cache_key = str(engine.url)
        now = time.monotonic()
        hit = _stats_cache.get(cache_key)
        if hit is not None and now - hit[0] < _STATS_CACHE_TTL:
            return hit[1]

        today = date.today()

        dates_result = await self.db.execute(
            select(Entry.entry_date)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                # Exclude year-1 tick-epoch artifacts (would poison streaks).
                Entry.entry_date >= date(2, 1, 1),
            )
            .distinct()
        )
        dates = sorted(d for (d,) in dates_result.all())

        total_entries_result = await self.db.execute(
            select(func.count())
            .select_from(Entry)
            .where(Entry.is_deleted == False)  # noqa: E712
        )
        total_entries = total_entries_result.scalar_one()

        words_result = await self.db.execute(
            select(Entry.body).where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_encrypted == False,  # noqa: E712
            )
        )
        total_words = sum(_word_count(body) for (body,) in words_result.all())

        mood_result = await self.db.execute(
            select(Entry.mood, func.count())
            .where(Entry.is_deleted == False, Entry.mood.is_not(None))  # noqa: E712
            .group_by(Entry.mood)
        )
        moods = [MoodCount(mood=mood, count=count) for mood, count in mood_result.all()]

        media_result = await self.db.execute(
            select(Media.media_type, func.count()).group_by(Media.media_type)
        )
        media = [MediaTypeCount(media_type=t, count=c) for t, c in media_result.all()]

        # Trailing N-week window, Monday-start, zero-filled.
        this_week = today - timedelta(days=today.weekday())
        per_week: Counter[date] = Counter()
        for d in dates:
            per_week[d - timedelta(days=d.weekday())] += 1
        weekly = [
            WeeklyCount(
                week_start=this_week - timedelta(weeks=i),
                count=per_week.get(this_week - timedelta(weeks=i), 0),
            )
            for i in range(weeks - 1, -1, -1)
        ]

        stats = JournalStatsResponse(
            total_entries=total_entries,
            total_words=total_words,
            current_streak=_current_streak(dates, today),
            longest_streak=_longest_streak(dates),
            weekly=weekly,
            moods=moods,
            media=media,
        )
        _stats_cache[cache_key] = (now, stats)
        return stats

    async def get_on_this_day(self, today: date) -> list[CalendarEntryResponse]:
        """Entries written on ``today``'s month/day in prior years.

        Same lightweight projection as the calendar month query (no body —
        titles/mood/tags only, tags batched in a second query). Year-1 rows
        (Diarium's .NET-tick epoch artifacts) are excluded via the
        ``>= date(2, 1, 1)`` bound rather than a per-row check.

        Feb 29 entries surface on Feb 28 of a non-leap year — the only day
        they'd otherwise never be shown on — so their anniversary is skipped
        in leap years alone, not silently dropped forever.
        """
        mmdd = today.strftime("%m-%d")
        patterns = [mmdd]
        if today.month == 2 and today.day == 28 and not _is_leap(today.year):
            patterns.append("02-29")

        rows_result = await self.db.execute(
            select(Entry.id, Entry.entry_date, Entry.title, Entry.mood, Entry.is_encrypted)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.entry_date >= date(2, 1, 1),
                Entry.entry_date < date(today.year, 1, 1),
                func.strftime("%m-%d", Entry.entry_date).in_(patterns),
            )
            .order_by(Entry.entry_date)
        )
        rows = rows_result.all()
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

        # Sanitise the query for FTS5 MATCH (shared helper quotes each token).
        from app.core.fts import sanitize_fts_query

        fts_query = sanitize_fts_query(query)

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
                    select(Entry).options(*_entry_list_options()).where(Entry.id.in_(entry_ids))
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
        base = (
            select(Entry)
            .options(*_entry_list_options())
            .where(
                Entry.is_deleted == False,  # noqa: E712
                (Entry.body.ilike(pattern)) | (Entry.title.ilike(pattern)),
            )
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
        Tag filtering uses an ``IN (subquery)`` rather than a join: an inner join
        to ``entry_tags`` emitted one row per matching tag, so an entry carrying
        two of the requested tags appeared twice in the list **and** inflated the
        total count.
        """
        if tag_ids:
            q = q.where(Entry.id.in_(select(EntryTag.entry_id).where(EntryTag.tag_id.in_(tag_ids))))
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
