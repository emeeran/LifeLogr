"""Entry import parsers for external formats.

Each parser returns a list of dicts shaped for the shared import loop in
``app.routers.entries``::

    {entry_date: str (YYYY-MM-DD), title: str | None, body: str,
     mood: str | None, tags: list[str], latitude?: float, longitude?: float}
"""

from app.services.importers.csv import parse_csv
from app.services.importers.diarium import parse_diarium_json_entry
from app.services.importers.dayone import parse_dayone_zip
from app.services.importers.markdown import parse_markdown_entry

__all__ = [
    "parse_csv",
    "parse_diarium_json_entry",
    "parse_dayone_zip",
    "parse_markdown_entry",
]
