"""Parser for Diarium JSON entry exports.

Extracted from ``app.routers.entries`` so the router stays a thin transport
layer. Pure function: a Diarium entry dict in, our import-shaped dict out.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_diarium_json_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Parse a single Diarium JSON entry into our import format."""
    # Diarium date format: "2026-01-15T00:00:00.0000000+00:00" or similar
    raw_date = str(item.get("date", ""))[:10]

    # Body: prefer "text" then "html" then "content"
    body = item.get("text", "") or item.get("content", "")
    if not body and item.get("html"):
        # Strip basic HTML tags for markdown body
        body = re.sub(r"<br\s*/?>", "\n", item["html"])
        body = re.sub(r"</?p>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body).strip()

    # Title from heading (may be HTML)
    title = item.get("heading", "")
    if title:
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title:
            title = None

    # Mood from rating (1-5 scale)
    mood = None
    rating = item.get("rating")
    if rating and isinstance(rating, (int, float)):
        moods = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}
        mood = moods.get(int(rating))

    tags = item.get("tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return {
        "entry_date": raw_date,
        "title": title,
        "body": body,
        "mood": mood,
        "tags": tags,
    }


def parse_diarium_sqlite(data: bytes) -> list[dict[str, Any]]:
    """Parse a Diarium ``.diary`` SQLite database (as bytes) into import dicts.

    Diarium stores ``DiaryEntryId`` as .NET ``DateTime.Ticks`` (100-nanosecond
    intervals since 0001-01-01); the offset ``621355968000000000`` converts that
    to Unix microseconds. Extracted from the entries router so the parsing is
    unit-testable and the router stays thin.
    """
    entries: list[dict[str, Any]] = []
    tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT e.DiaryEntryId, e.Heading, e.Text, e.Rating, e.Latitude, e.Longitude "
            "FROM Entries e ORDER BY e.DiaryEntryId"
        ).fetchall()
        tag_rows = conn.execute(
            "SELECT et.DiaryEntryId, t.Value FROM EntryTags et "
            "JOIN Tags t ON et.DiaryTagId = t.DiaryTagId"
        ).fetchall()
        entry_tags_map: dict[int, list[str]] = {}
        for tr in tag_rows:
            entry_tags_map.setdefault(tr["DiaryEntryId"], []).append(tr["Value"])

        for row in rows:
            ticks = row["DiaryEntryId"]
            try:
                us = (ticks - 621355968000000000) / 10
                entry_date_str = datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
            except Exception:
                logger.warning("Failed to parse Diarium date (ticks=%s)", ticks)
                continue

            heading = re.sub(r"<[^>]+>", "", row["Heading"] or "").strip() or None
            body_text = row["Text"] or ""
            if body_text:
                body_text = re.sub(r"<br\s*/?>", "\n", body_text)
                body_text = re.sub(r"</?p>", "\n", body_text)
                body_text = re.sub(r"<[^>]+>", "", body_text).strip()

            if not body_text:
                continue

            if heading == "Today's Summary":
                heading = None

            mood_val = None
            rating = row["Rating"]
            if rating and isinstance(rating, (int, float)) and 1 <= int(rating) <= 5:
                mood_val = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}.get(int(rating))

            entries.append(
                {
                    "entry_date": entry_date_str,
                    "title": heading,
                    "body": body_text,
                    "mood": mood_val,
                    "tags": entry_tags_map.get(row["DiaryEntryId"], []),
                    "latitude": row["Latitude"] if row["Latitude"] else None,
                    "longitude": row["Longitude"] if row["Longitude"] else None,
                }
            )
        conn.close()
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return entries
