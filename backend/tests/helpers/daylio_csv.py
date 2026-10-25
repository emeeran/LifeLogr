"""Synthetic Daylio CSV builder for tests.

Produces CSV text with Daylio's real export header so import tests exercise
the exact shape the app emits and consumes (see ``export_service.build_daylio_csv``
for the export side).
"""

from __future__ import annotations

import csv
import io

# Daylio's export header, verbatim.
DAYLIO_HEADER = [
    "full_date",
    "date",
    "weekday",
    "time",
    "mood",
    "activities",
    "note_title",
    "note",
]


def build_daylio_csv(rows: list[dict[str, str]]) -> str:
    """Build Daylio CSV text from partial row dicts (missing cells empty)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=DAYLIO_HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in DAYLIO_HEADER})
    return buf.getvalue()
