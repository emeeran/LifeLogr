"""Parser for Diarium JSON entry exports.

Extracted from ``app.routers.entries`` so the router stays a thin transport
layer. Pure function: a Diarium entry dict in, our import-shaped dict out.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_diarium_json_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Parse a single Diarium JSON entry into our import format.

    Accepts both spellings seen in the wild: our own lowercase interchange
    shape (``date``/``text``/``heading``/``rating``/``tags``) and Diarium's
    object model, which is keyed on ``DiaryEntryId`` (.NET ticks — the same
    identity the database uses; its JSON import reads ids back with SQLite's
    ``json_each``) with ``Text``/``Heading``/``Rating``/``Tags`` capitalized.
    """
    raw_date: str = ""

    # Real Diarium shape: DiaryEntryId is the timestamp in .NET ticks.
    ticks = item.get("DiaryEntryId")
    if ticks:
        try:
            dt = datetime(1, 1, 1) + timedelta(microseconds=int(ticks) / 10)
            raw_date = dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            logger.warning("Invalid DiaryEntryId ticks in JSON entry: %s", ticks)
    if not raw_date:
        # Our interchange shape: "2026-01-15T00:00:00.0000000+00:00" or YYYY-MM-DD.
        raw_date = str(item.get("date", ""))[:10]

    # Body: prefer "text"/"Text" then "html" then "content". Real Diarium
    # files capitalize (its Text column is HTML — strip tags); our interchange
    # JSON uses lowercase "text" holding plain markdown, kept verbatim.
    body = item.get("text") or item.get("content") or ""
    if not isinstance(body, str):
        body = ""
    html_body = item.get("Text") or item.get("html") or ""
    if not body and html_body:
        body = re.sub(r"<br\s*/?>", "\n", html_body)
        body = re.sub(r"</?p>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body).strip()

    # Title from heading (may be HTML)
    title = item.get("heading") or item.get("Heading") or ""
    if title:
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title:
            title = None

    # Mood from rating (1-5 scale)
    mood = None
    rating = item.get("rating") or item.get("Rating")
    if rating and isinstance(rating, (int, float)):
        moods = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}
        mood = moods.get(int(rating))

    tags = item.get("tags") or item.get("Tags") or []
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

    Real Diarium backups (schema verified against the shipped 3.3.12.0 binary)
    carry more than we import — Events (weather), Media blobs, Templates —
    which are skipped: LifeLogr import carries text, mood, tags and geotags.
    ``Tags.Type`` distinguishes 0 = tag, 1 = person, 2 = tracker; tags and
    persons both import as LifeLogr tags, trackers (boolean check-off items
    whose Value is the activity name and whose per-entry state lives in
    EntryTags.TrackingValue) are skipped as noise.
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
        # Filter tracker tags only when the file actually carries the Type
        # column — hand-made or very old databases may predate it.
        has_tag_type = any(
            r[1] == "Type" for r in conn.execute("PRAGMA table_info(Tags)").fetchall()
        )
        tag_sql = (
            "SELECT et.DiaryEntryId, t.Value FROM EntryTags et "
            "JOIN Tags t ON et.DiaryTagId = t.DiaryTagId"
        )
        if has_tag_type:
            tag_sql += " WHERE t.Type IS NULL OR t.Type IN (0, 1)"
        tag_rows = conn.execute(tag_sql).fetchall()

        # Media blobs (photos, audio, documents) — re-attached to the imported
        # entry. DiaryMediaId is a GUID we don't need; Type maps back to our
        # categories (0 image, 1 audio, 2 unknown, 3 document, 4 video).
        _MEDIA_TYPE_FROM_DIARIUM = {0: "image", 1: "audio", 2: "document", 3: "document", 4: "video"}
        media_map: dict[int, list[dict[str, Any]]] = {}
        try:
            for mr in conn.execute(
                'SELECT DiaryEntryId, Type, Data, Name, FileEnding FROM Media '
                'ORDER BY DiaryEntryId, "Index"'
            ).fetchall():
                data = mr["Data"] or b""
                if not data:
                    continue
                media_map.setdefault(mr["DiaryEntryId"], []).append(
                    {
                        "filename": f"{mr['Name']}{mr['FileEnding'] or ''}",
                        "media_type": _MEDIA_TYPE_FROM_DIARIUM.get(
                            mr["Type"] if mr["Type"] is not None else 3, "document"
                        ),
                        "data": data,
                    }
                )
        except sqlite3.OperationalError:
            logger.info("No Media table in .diary file — importing text only")
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

            if not body_text and not media_map.get(row["DiaryEntryId"]):
                # Photo-only entries (empty text) survive via their media; a
                # truly empty entry is noise.
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
                    "media": media_map.get(row["DiaryEntryId"], []),
                }
            )
        conn.close()
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return entries
