"""AnalyticsService — journal statistics and insights."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.models.media import Media
from app.models.recording import VoiceRecording
from app.models.sentiment import EntrySentiment
from app.models.tag import EntryTag, Tag
from app.schemas.analytics import (
    HeatmapDayResponse,
    HeatmapResponse,
    MediaStatsResponse,
    MoodDistributionResponse,
    OverviewResponse,
    TagStatsResponse,
    WordCountResponse,
    WritingHabitResponse,
)


def _word_count_expr():
    """Approximate SQL word count: body length minus spaces, plus one."""
    body = Entry.body
    return func.length(body) - func.length(func.replace(body, " ", "")) + 1


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(self) -> OverviewResponse:
        """High-level journal statistics."""
        base = select(Entry).where(Entry.is_deleted == False)  # noqa: E712

        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        words_result = (
            await self.db.execute(
                select(
                    func.sum(_word_count_expr())
                ).where(Entry.is_deleted == False)  # noqa: E712
            )
        ).scalar()
        total_words = int(words_result or 0)

        total_media = (await self.db.execute(select(func.count()).select_from(Media))).scalar_one()

        total_recordings = (
            await self.db.execute(select(func.count()).select_from(VoiceRecording))
        ).scalar_one()

        date_range = (
            await self.db.execute(
                select(func.min(Entry.entry_date), func.max(Entry.entry_date)).where(
                    Entry.is_deleted.is_(False)
                )
            )
        ).one()
        start, end = date_range

        # Calculate streaks
        dates_result = await self.db.execute(
            select(Entry.entry_date)
            .where(Entry.is_deleted == False)  # noqa: E712
            .order_by(Entry.entry_date)
        )
        all_dates = [row[0] for row in dates_result]
        longest, current = self._calc_streaks(all_dates)

        return OverviewResponse(
            total_entries=total,
            total_words=total_words,
            total_media=total_media,
            total_recordings=total_recordings,
            date_range_start=start,
            date_range_end=end,
            longest_streak=longest,
            current_streak=current,
        )

    async def writing_habits(self) -> list[WritingHabitResponse]:
        """Entry count per day of week."""
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        result = await self.db.execute(
            select(
                func.cast(func.strftime("%w", Entry.entry_date), Integer),
                func.count(),
            )
            .where(Entry.is_deleted == False)  # noqa: E712
            .group_by(func.cast(func.strftime("%w", Entry.entry_date), Integer))
        )
        mapping = {row[0]: row[1] for row in result}
        # SQLite %w: 0=Sunday, convert to 0=Monday
        responses = []
        for i in range(7):
            # Convert Monday-indexed (0=Mon) to SQLite %w (0=Sun)
            sqlite_dow = (i + 1) % 7
            responses.append(
                WritingHabitResponse(
                    day_of_week=i,
                    day_name=day_names[i],
                    entry_count=mapping.get(sqlite_dow, 0),
                )
            )
        return responses

    async def word_counts(self) -> WordCountResponse:
        """Word count statistics."""
        rows = (
            await self.db.execute(
                select(
                    func.sum(_word_count_expr()).label("total"),
                    func.avg(_word_count_expr()).label("avg"),
                    func.max(_word_count_expr()).label("longest"),
                    func.min(_word_count_expr()).label("shortest"),
                ).where(Entry.is_deleted == False)  # noqa: E712
            )
        ).one()
        return WordCountResponse(
            total_words=int(rows.total or 0),
            average_words_per_entry=round(float(rows.avg or 0), 1),
            longest_entry_words=int(rows.longest or 0),
            shortest_entry_words=int(rows.shortest or 0),
        )

    async def tag_stats(self) -> list[TagStatsResponse]:
        """Tag usage counts (excludes soft-deleted entries)."""
        result = await self.db.execute(
            select(Tag.id, Tag.name, func.count(EntryTag.entry_id).label("cnt"))
            .join(EntryTag, Tag.id == EntryTag.tag_id)
            .join(Entry, Entry.id == EntryTag.entry_id)
            .where(Entry.is_deleted == False)  # noqa: E712
            .group_by(Tag.id)
            .order_by(func.count(EntryTag.entry_id).desc())
        )
        return [
            TagStatsResponse(tag_id=row.id, tag_name=row.name, usage_count=row.cnt)
            for row in result
        ]

    async def mood_distribution(self) -> list[MoodDistributionResponse]:
        """Mood frequency distribution."""
        result = await self.db.execute(
            select(Entry.mood, func.count().label("cnt"))
            .where(Entry.is_deleted == False, Entry.mood.is_not(None))  # noqa: E712
            .group_by(Entry.mood)
            .order_by(func.count().desc())
        )
        total = sum(row.cnt for row in result)
        return [
            MoodDistributionResponse(
                mood=row.mood,
                count=row.cnt,
                percentage=round(row.cnt / total * 100, 1) if total else 0,
            )
            for row in result
        ]

    async def heatmap(self, year: int | None = None) -> HeatmapResponse:
        """Year-long contribution heatmap."""
        if year is None:
            year = date.today().year
        result = await self.db.execute(
            select(Entry.entry_date, func.count().label("cnt"))
            .where(
                Entry.is_deleted == False,  # noqa: E712
                func.strftime("%Y", Entry.entry_date) == str(year),
            )
            .group_by(Entry.entry_date)
        )
        day_map = {row.entry_date: row.cnt for row in result}
        days = [
            HeatmapDayResponse(date=d, count=day_map.get(d, 0))
            for d in (date(year, 1, 1) + timedelta(n) for n in range(366))
            if d.year == year
        ]
        return HeatmapResponse(year=year, days=days)

    async def media_stats(self) -> MediaStatsResponse:
        """Media usage statistics."""
        images = (
            await self.db.execute(
                select(func.count()).select_from(Media).where(Media.media_type == "image")
            )
        ).scalar_one()

        videos = (
            await self.db.execute(
                select(func.count()).select_from(Media).where(Media.media_type == "video")
            )
        ).scalar_one()

        recordings = (
            await self.db.execute(select(func.count()).select_from(VoiceRecording))
        ).scalar_one()

        total_size = (
            await self.db.execute(select(func.coalesce(func.sum(Media.file_size), 0)))
        ).scalar_one()

        return MediaStatsResponse(
            total_images=images,
            total_videos=videos,
            total_recordings=recordings,
            total_size_bytes=total_size,
        )

    async def sentiment_timeline(self, year: int, month: int) -> list[dict[str, object]]:
        """Valence over time for AI-analyzed entries within a given month."""
        result = await self.db.execute(
            select(
                Entry.entry_date,
                EntrySentiment.valence,
                EntrySentiment.primary_emotion,
                EntrySentiment.intensity,
            )
            .join(EntrySentiment, Entry.id == EntrySentiment.entry_id)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                func.strftime("%Y", Entry.entry_date) == str(year),
                func.strftime("%m", Entry.entry_date) == f"{month:02d}",
            )
            .order_by(Entry.entry_date)
        )
        return [
            {
                "entry_date": str(row.entry_date),
                "valence": row.valence,
                "primary_emotion": row.primary_emotion,
                "intensity": row.intensity,
            }
            for row in result
        ]

    @staticmethod
    def _calc_streaks(dates: list[date]) -> tuple[int, int]:
        """Calculate longest and current writing streaks."""
        if not dates:
            return 0, 0

        date_set = set(dates)
        longest = 0
        current = 0

        # Current streak: count backwards from today
        today = date.today()
        d = today
        while d in date_set:
            current += 1
            d -= timedelta(days=1)

        # Longest streak
        for d in sorted(date_set):
            streak = 1
            next_d = d + timedelta(days=1)
            while next_d in date_set:
                streak += 1
                next_d += timedelta(days=1)
            longest = max(longest, streak)

        return longest, current
