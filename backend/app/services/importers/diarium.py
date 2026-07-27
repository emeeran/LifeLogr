"""Parser for Diarium JSON entry exports.

Extracted from ``app.routers.entries`` so the router stays a thin transport
layer. Pure function: a Diarium entry dict in, our import-shaped dict out.
"""

from __future__ import annotations

import re
from typing import Any


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
