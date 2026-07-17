"""Pydantic schemas for analytics endpoints."""

from datetime import date

from pydantic import BaseModel


class OverviewResponse(BaseModel):
    """High-level journal statistics."""

    total_entries: int
    total_words: int
    total_media: int
    total_recordings: int
    date_range_start: date | None
    date_range_end: date | None
    longest_streak: int
    current_streak: int


class WritingHabitResponse(BaseModel):
    """Writing frequency per day-of-week."""

    day_of_week: int  # 0=Monday .. 6=Sunday
    day_name: str
    entry_count: int


class WordCountResponse(BaseModel):
    """Word count stats."""

    total_words: int
    average_words_per_entry: float
    longest_entry_words: int
    shortest_entry_words: int


class TagStatsResponse(BaseModel):
    """Tag usage statistics."""

    tag_id: int
    tag_name: str
    usage_count: int


class MoodDistributionResponse(BaseModel):
    """Mood frequency distribution."""

    mood: str
    count: int
    percentage: float


class HeatmapDayResponse(BaseModel):
    """Single day in the contribution heatmap."""

    date: date
    count: int


class HeatmapResponse(BaseModel):
    """Year-long contribution heatmap."""

    year: int
    days: list[HeatmapDayResponse]


class MediaStatsResponse(BaseModel):
    """Media usage statistics."""

    total_images: int
    total_videos: int
    total_recordings: int
    total_size_bytes: int
