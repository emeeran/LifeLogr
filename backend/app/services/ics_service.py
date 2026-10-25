"""Read-only ICS (iCalendar) parsing for the composer context sidebar.

A deliberately small RFC 5545 reader: line unfolding, VEVENT walking (with
VALARM blocks ignored), ``VALUE=DATE`` all-day handling, UTC/TZID datetimes,
and TEXT unescaping. Recurring events are emitted **once, at their first
occurrence**, with a warning surfaced to the caller — expanding RRULEs is out
of scope for a read-only preview.

Pure function, no dependencies: ``parse_ics`` takes calendar text and returns
``{"events": [...], "warnings": [...]}``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

_TEXT_ESCAPES = {"\\n": "\n", "\\N": "\n", "\\,": ",", "\\;": ";", "\\\\": "\\"}


def _unfold(text: str) -> list[str]:
    """RFC 5545 §3.1: a CRLF (or LF) followed by a space/tab is a continuation."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _split_property(line: str) -> tuple[str, dict[str, str], str] | None:
    """Split ``NAME;PARAM=VAL;...:value`` — colons inside quotes don't split."""
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            name_params, value = line[:i], line[i + 1 :]
            parts = name_params.split(";")
            params: dict[str, str] = {}
            for param in parts[1:]:
                key, _, val = param.partition("=")
                params[key.upper()] = val.strip('"')
            return parts[0].upper(), params, value
    return None


def _unescape_text(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        two = value[i : i + 2]
        if two in _TEXT_ESCAPES:
            out.append(_TEXT_ESCAPES[two])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _parse_dt(params: dict[str, str], value: str) -> tuple[str, bool]:
    """Parse a DTSTART/DTEND value → ``(iso_string, all_day)``.

    ``VALUE=DATE`` (``YYYYMMDD``) is all-day. Naive datetimes stay naive;
    ``Z``-suffixed UTC values convert to the server's local zone so they sort
    naturally against the (local) entry dates.
    """
    value = value.strip()
    if params.get("VALUE") == "DATE" or "T" not in value:
        return datetime.strptime(value[:8], "%Y%m%d").date().isoformat(), True
    if value.endswith("Z"):
        dt = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None).isoformat(), False
    # TZID or floating — both stay as the written wall time.
    return datetime.strptime(value, "%Y%m%dT%H%M%S").isoformat(), False


def _end_from_duration(props: dict[str, tuple[dict[str, str], str]]) -> str | None:
    """DURATION-form events (``DURATION:PT1H30M``) → an end ISO string."""
    duration = props.get("DURATION")
    start = props.get("DTSTART")
    if duration is None or start is None:
        return None
    value = duration[1].strip()
    m = re.fullmatch(
        r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value
    )
    if m is None:
        return None
    sign, weeks, days, hours, minutes, seconds = m.groups()
    delta = timedelta(
        weeks=int(weeks or 0),
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(seconds or 0),
    )
    if sign == "-":
        delta = -delta
    start_iso, all_day = _parse_dt(*start)
    start_dt = datetime.fromisoformat(start_iso)
    if all_day:
        return (start_dt + delta).date().isoformat()
    return (start_dt + delta).isoformat()


def parse_ics(text: str) -> dict[str, Any]:
    """Parse ICS *text* → ``{"events": [...], "warnings": [...]}``.

    Events: ``{uid, summary, start, end, all_day, location, description}``
    (``start``/``end`` are ISO strings; ``end`` honours ``DTEND`` or
    ``DURATION``, defaulting to ``None``). Recurring events appear once with a
    warning; VALARM sub-blocks are ignored.
    """
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    recurring = False

    props: dict[str, tuple[dict[str, str], str]] = {}
    depth_stack: list[str] = []
    in_event = False

    def _flush() -> None:
        nonlocal recurring
        if "DTSTART" not in props:
            return  # a VEVENT without a start is not renderable
        start_iso, all_day = _parse_dt(*props["DTSTART"])
        if "DTEND" in props:
            end_iso, _ = _parse_dt(*props["DTEND"])
        else:
            end_iso = _end_from_duration(props)
        if "RRULE" in props and not recurring:
            warnings.append(
                "Recurring events are shown once, at their first occurrence."
            )
            recurring = True
        events.append(
            {
                "uid": props.get("UID", ("", ""))[1] or None,
                "summary": _unescape_text(props.get("SUMMARY", ("", ""))[1]) or "(untitled event)",
                "start": start_iso,
                "end": end_iso,
                "all_day": all_day,
                "location": _unescape_text(props.get("LOCATION", ("", ""))[1]) or None,
                "description": _unescape_text(props.get("DESCRIPTION", ("", ""))[1]) or None,
            }
        )

    for line in _unfold(text):
        if line.startswith("#") or not line.strip():
            continue
        stripped = line.strip().upper()
        if stripped == "BEGIN:VEVENT":
            in_event = True
            props = {}
            continue
        if stripped == "END:VEVENT":
            _flush()
            in_event = False
            continue
        if not in_event:
            continue
        if stripped == "BEGIN:VALARM":
            depth_stack.append("VALARM")
            continue
        if stripped == "END:VALARM":
            if depth_stack:
                depth_stack.pop()
            continue
        if depth_stack:
            continue  # inside VALARM — skip its properties
        parsed = _split_property(line)
        if parsed is None:
            continue
        name, params, value = parsed
        props[name] = (params, value)

    return {"events": events, "warnings": warnings}
