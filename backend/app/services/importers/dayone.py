"""Day One JSON export import.

Day One's "Export to JSON" produces a ZIP containing ``Journal.json`` (with an
``entries`` array) plus a ``photos/`` folder. We import text + metadata + tags
+ location; media attachment is a follow-up.

Entry fields used:
  creationDate -> entry_date   text -> body   title -> title
  tags -> tags                 location.{latitude,longitude} -> lat/lng
"""

from __future__ import annotations

import io
import json
import zipfile


def _load_journal(zf: zipfile.ZipFile) -> dict | None:
    """Find and parse Journal.json inside the export ZIP, else None."""
    for name in zf.namelist():
        if name.endswith("Journal.json"):
            try:
                data = json.loads(zf.read(name))
            except Exception:
                return None
            return data if isinstance(data, dict) else None
    return None


def parse_dayone_zip(content: bytes) -> list[dict]:
    """Parse a Day One export ZIP into entry dicts (empty on non-Day One ZIP)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content), "r")
    except zipfile.BadZipFile:
        return []

    out: list[dict] = []
    with zf:
        journal = _load_journal(zf)
        if journal is None:
            return out
        entries = journal.get("entries") or []
        for e in entries:
            date_raw = str(e.get("creationDate", ""))[:10]
            body = (e.get("text") or "").strip()
            if not date_raw or not body:
                continue
            title = (e.get("title") or "").strip() or None
            tags = e.get("tags") or []
            loc = e.get("location") or {}
            out.append(
                {
                    "entry_date": date_raw,
                    "title": title,
                    "body": body,
                    "mood": None,
                    "tags": list(tags),
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                }
            )
    return out
