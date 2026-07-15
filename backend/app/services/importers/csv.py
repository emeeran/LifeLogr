"""CSV import with flexible header mapping.

Expects at least a date column and a body/text column. Recognised headers
(case-insensitive):

  date:   date | entry_date | datetime
  title:  title | heading
  body:   body | text | content | entry | note | journal
  mood:   mood | rating | feeling      (rating 1-5 maps to the 5-mood scale)
  tags:   tags | tag                   (split on ; | or ,)
"""

from __future__ import annotations

import csv
import io
import re

_DATE_KEYS = {"date", "entry_date", "entry date", "datetime"}
_TITLE_KEYS = {"title", "heading"}
_BODY_KEYS = {"body", "text", "content", "entry", "note", "journal"}
_MOOD_KEYS = {"mood", "rating", "feeling"}
_TAG_KEYS = {"tags", "tag"}

_RATING_TO_MOOD = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}


def _field(row: dict[str, str | None], keys: set[str]) -> str | None:
    """First non-empty value whose header matches one of *keys* (case-insensitive)."""
    for header, value in row.items():
        if header is None or value is None:
            continue
        if header.strip().lower() in keys:
            return value
    return None


def parse_csv(text: str) -> list[dict[str, str | None | list[str]]]:
    """Parse CSV *text* into entry dicts. Rows lacking date/body are skipped."""
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel  # sensible default (comma-delimited)

    out: list[dict[str, str | None | list[str]]] = []
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    for row in reader:
        date_raw = _field(row, _DATE_KEYS)
        body = (_field(row, _BODY_KEYS) or "").strip()
        if not date_raw or not body:
            continue

        title = (_field(row, _TITLE_KEYS) or "").strip() or None

        mood = None
        mood_raw = _field(row, _MOOD_KEYS)
        if mood_raw:
            m = str(mood_raw).strip().lower()
            if m in _RATING_TO_MOOD.values():
                mood = m
            elif m.isdigit() and int(m) in _RATING_TO_MOOD:
                mood = _RATING_TO_MOOD[int(m)]

        tags_raw = _field(row, _TAG_KEYS) or ""
        tags = [t.strip() for t in re.split(r"[;|,]", tags_raw) if t.strip()]

        out.append(
            {
                "entry_date": str(date_raw).strip()[:10],
                "title": title,
                "body": body,
                "mood": mood,
                "tags": tags,
            }
        )
    return out
