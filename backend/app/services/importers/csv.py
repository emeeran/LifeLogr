"""CSV import with flexible header mapping.

Expects at least a date column. Recognised headers (case-insensitive):

  date:   date | entry_date | datetime
  title:  title | heading | note_title
  body:   body | text | content | entry | note | journal
  mood:   mood | rating | feeling      (rating 1-5 maps to the 5-mood scale)
  tags:   tags | tag | activities      (Daylio separates with " | ")

Real Daylio exports (``full_date,date,weekday,time,mood,activities,
note_title,note``) are a primary target: mood-only check-ins (empty note)
are real entries, activity names split on ``" | "`` into tags, and the
mood-icon vocabulary maps onto the 5-word scale (``rad``/``okay``/``so-so``).
The ``weekday`` and ``time`` columns are ignored — entries are day-granular.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date as date_type
from datetime import datetime as datetime_type

_DATE_KEYS = {"date", "full_date", "entry_date", "entry date", "datetime"}
_TITLE_KEYS = {"title", "heading", "note_title"}
_BODY_KEYS = {"body", "text", "content", "entry", "note", "journal"}
_MOOD_KEYS = {"mood", "rating", "feeling"}
_TAG_KEYS = {"tags", "tag", "activities"}

_RATING_TO_MOOD = {1: "awful", 2: "bad", 3: "meh", 4: "good", 5: "great"}
# Daylio spells the top of its 5-point scale "rad" and its middle "okay" (or
# "so-so" in older versions). All collapse onto LifeLogr's five words.
_MOOD_WORD_ALIASES = {"rad": "great", "okay": "meh", "so-so": "meh"}

_DATE_FORMATS = ("%b %d, %Y", "%m/%d/%Y")  # after ISO, incl. Daylio's full_date


def _parse_date(raw: str) -> str | None:
    """Normalize a date cell to ISO ``YYYY-MM-DD``; ``None`` when unparsable.

    Daylio's ``full_date`` is human-readable ("May 1, 2021") while other
    exporters use ISO or US order — guessing the format beats slicing the
    first 10 chars off a non-ISO value.
    """
    value = raw.strip()
    if not value:
        return None
    try:
        return date_type.fromisoformat(value[:10]).isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime_type.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _field(row: dict[str, str | None], keys: set[str]) -> str | None:
    """First non-empty value whose header matches one of *keys* (case-insensitive)."""
    for header, value in row.items():
        if header is None or value is None:
            continue
        if header.strip().lower() in keys:
            return value
    return None


def _tag_header(row: dict[str, str | None]) -> str:
    """The header name the tags value was found under (first match)."""
    for header in row:
        if header is not None and header.strip().lower() in _TAG_KEYS:
            return header
    return ""


def _split_tag_cell(raw: str, header: str) -> list[str]:
    """Split a tags/activities cell into names.

    Daylio joins *activities* with ``" | "``, and activity names may themselves
    contain commas ("Coffee with Ann, downtown") — so for that column the pipe
    is authoritative. Generic ``tags``/``tag`` columns keep the legacy
    ``;``,`` split (which also handles pipes).
    """
    if header.strip().lower() == "activities":
        parts = raw.split("|")
    else:
        parts = re.split(r"[;|,]", raw)
    return [p.strip() for p in parts if p.strip()]


def parse_csv(text: str) -> list[dict[str, object]]:
    """Parse CSV *text* into entry dicts.

    Rows lacking a date (or an unparsable one) come back as placeholder dicts
    with an ``error`` key so the import pipeline reports them in
    ``skip_reasons`` rather than silently dropping them. A row with no body is
    still a real entry when it carries a mood or activities — Daylio
    mood-only check-ins.
    """
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel  # sensible default (comma-delimited)

    out: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    for row in reader:
        date_raw = _field(row, _DATE_KEYS)
        title = (_field(row, _TITLE_KEYS) or "").strip() or None
        body = (_field(row, _BODY_KEYS) or "").strip()

        mood = None
        mood_raw = _field(row, _MOOD_KEYS)
        if mood_raw:
            m = str(mood_raw).strip().lower()
            if m in _MOOD_WORD_ALIASES:
                mood = _MOOD_WORD_ALIASES[m]
            elif m in _RATING_TO_MOOD.values():
                mood = m
            elif m.isdigit() and int(m) in _RATING_TO_MOOD:
                mood = _RATING_TO_MOOD[int(m)]

        tags = _split_tag_cell(_field(row, _TAG_KEYS) or "", _tag_header(row))

        entry_date = _parse_date(date_raw) if date_raw else None
        if entry_date is None:
            out.append(
                {
                    "entry_date": None,
                    "title": title,
                    "body": body,
                    "mood": mood,
                    "tags": tags,
                    "error": f"unparsable date {date_raw!r}",
                }
            )
            continue
        if not body and mood is None and not tags:
            continue  # nothing to import — not a check-in at all

        out.append(
            {
                "entry_date": entry_date,
                "title": title,
                "body": body,
                "mood": mood,
                "tags": tags,
            }
        )
    return out
