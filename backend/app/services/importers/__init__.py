"""Entry import parsers for external formats.

Each parser returns a list of dicts shaped for the shared import loop in
``app.routers.entries``::

    {entry_date: str (YYYY-MM-DD), title: str | None, body: str,
     mood: str | None, tags: list[str], latitude?: float, longitude?: float}
"""

from app.services.importers.csv import parse_csv
from app.services.importers.dayone import parse_dayone_zip

__all__ = ["parse_csv", "parse_dayone_zip"]
