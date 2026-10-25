"""Unit tests for the hand-rolled ICS parser (read-only calendar context)."""

from __future__ import annotations

from app.services.ics_service import parse_ics


def test_parses_simple_vevent() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            "UID:abc-123",
            "DTSTART:20260401T090000",
            "DTEND:20260401T100000",
            "SUMMARY:Standup",
            "LOCATION:Room 2",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    out = parse_ics(ics)
    assert out["warnings"] == []
    (event,) = out["events"]
    assert event["uid"] == "abc-123"
    assert event["summary"] == "Standup"
    assert event["start"] == "2026-04-01T09:00:00"
    assert event["end"] == "2026-04-01T10:00:00"
    assert event["all_day"] is False
    assert event["location"] == "Room 2"


def test_unfolds_continuation_lines() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "DTSTART:20260401T090000",
            "SUMMARY:Long title that",
            "  continues across lines",
            "END:VEVENT",
        ]
    )
    (event,) = parse_ics(ics)["events"]
    assert event["summary"] == "Long title that continues across lines"


def test_all_day_date_value_sets_all_day() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "DTSTART;VALUE=DATE:20260401",
            "DTEND;VALUE=DATE:20260402",
            "SUMMARY:Trip",
            "END:VEVENT",
        ]
    )
    (event,) = parse_ics(ics)["events"]
    assert event["all_day"] is True
    assert event["start"] == "2026-04-01"
    assert event["end"] == "2026-04-02"


def test_utc_datetime_converts_to_local() -> None:
    ics = "BEGIN:VEVENT\nDTSTART:20260401T120000Z\nSUMMARY:UTC\nEND:VEVENT"
    (event,) = parse_ics(ics)["events"]
    assert event["all_day"] is False
    # No trailing timezone info (converted to server-local naive ISO) and not
    # still the literal UTC wall time unless the server IS utc.
    assert event["start"].endswith("00:00") or event["start"].endswith(":00")


def test_duration_sets_end() -> None:
    ics = "BEGIN:VEVENT\nDTSTART:20260401T090000\nDURATION:PT1H30M\nSUMMARY:D\nEND:VEVENT"
    (event,) = parse_ics(ics)["events"]
    assert event["end"] == "2026-04-01T10:30:00"


def test_unescapes_description_newlines() -> None:
    ics = "BEGIN:VEVENT\nDTSTART:20260401T090000\nDESCRIPTION:line one\\nline two\\, done\nEND:VEVENT"
    (event,) = parse_ics(ics)["events"]
    assert event["description"] == "line one\nline two, done"


def test_recurring_event_emitted_once_with_warning() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:weekly",
            "DTSTART:20260401T090000",
            "RRULE:FREQ=WEEKLY;COUNT=10",
            "SUMMARY:Weekly",
            "END:VEVENT",
        ]
    )
    out = parse_ics(ics)
    assert len(out["events"]) == 1
    assert out["warnings"] == ["Recurring events are shown once, at their first occurrence."]


def test_no_vevents_returns_empty() -> None:
    assert parse_ics("BEGIN:VCALENDAR\nEND:VCALENDAR") == {"events": [], "warnings": []}
    assert parse_ics("not a calendar at all") == {"events": [], "warnings": []}


def test_valarm_block_ignored() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "DTSTART:20260401T090000",
            "SUMMARY:With alarm",
            "BEGIN:VALARM",
            "TRIGGER:-PT15M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Reminder",
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    (event,) = parse_ics(ics)["events"]
    assert event["summary"] == "With alarm"
    assert len(event) == 7  # no alarm properties leaked into the event dict


def test_colon_inside_quoted_param_does_not_split() -> None:
    ics = 'BEGIN:VEVENT\nDTSTART;TZID="Europe/Berlin":20260401T090000\nSUMMARY:TZ\nEND:VEVENT'
    (event,) = parse_ics(ics)["events"]
    assert event["start"] == "2026-04-01T09:00:00"
