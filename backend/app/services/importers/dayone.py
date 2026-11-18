"""Day One JSON export import.

Day One's "Export to JSON" produces a ZIP containing ``Journal.json`` (with an
``entries`` array) plus a ``photos/`` folder. We import text + metadata + tags
+ location + photos: each entry's ``photos`` array references members by
``md5`` (``photos/<md5>.jpeg``), which we resolve against a basename index of
the ZIP and attach through the standard import-media pipeline.

Entry fields used:
  creationDate -> entry_date   text -> body   title -> title
  tags -> tags                 location.{latitude,longitude} -> lat/lng
  photos[].{md5,type,caption}  -> media items
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

# A hostile/oversized Journal.json must not be decompressed wholesale into
# memory; anything above this is refused (the entry is skipped, not fatal).
_MAX_MEMBER_BYTES = 64 * 1024 * 1024

# Day One photo members are hex md5 stems; thumbnail variants carry a suffix.
_THUMB_SUFFIX_RE = re.compile(r"-(?:thumb|thumbnail)$")


def _load_journal(zf: zipfile.ZipFile) -> dict[str, Any] | None:
    """Find and parse Journal.json inside the export ZIP, else None."""
    for name in zf.namelist():
        if name.endswith("Journal.json"):
            if zf.getinfo(name).file_size > _MAX_MEMBER_BYTES:
                logger.warning(
                    "Skipping oversized Day One Journal.json (%d bytes)",
                    zf.getinfo(name).file_size,
                )
                return None
            try:
                data = json.loads(zf.read(name))
            except Exception:
                return None
            return data if isinstance(data, dict) else None
    return None


def _photo_index(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map photo basename-without-extension -> ZIP member name.

    Day One export layouts vary by version (``photos/<md5>.jpeg`` flat, or
    nested under year folders) — matching on the basename handles both.
    Thumbnail members (``<md5>-thumb.jpeg``) are indexed under their md5 too,
    but a full-size member registered later overwrites them, so the best
    variant wins regardless of member order.
    """
    index: dict[str, str] = {}
    for name in zf.namelist():
        parts = name.split("/")
        base = parts[-1]
        if not base or "photos" not in parts[:-1]:
            continue
        stem, dot, ext = base.rpartition(".")
        if not dot or not ext:
            continue
        key = _THUMB_SUFFIX_RE.sub("", stem).lower()
        if len(key) != 32:  # md5 hex length — ignore anything else
            continue
        full = not _THUMB_SUFFIX_RE.search(stem)
        if full or key not in index:
            index[key] = name
    return index


def _media_for_photos(
    zf: zipfile.ZipFile, index: dict[str, str], entry: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resolve an entry's ``photos`` references into import-media payloads.

    A photo that is hidden, unresolvable in the ZIP, or oversized is skipped
    with a log line — never at the cost of the entry itself.
    """
    items: list[dict[str, Any]] = []
    for photo in entry.get("photos") or []:
        if not isinstance(photo, dict) or photo.get("hidden"):
            continue
        md5 = str(photo.get("md5") or "").strip().lower()
        if not md5:
            continue
        member = index.get(md5)
        if member is None:
            logger.warning("Day One photo %s not found in export ZIP — skipped", md5)
            continue
        if zf.getinfo(member).file_size > _MAX_MEMBER_BYTES:
            logger.warning("Day One photo %s oversized (%d bytes) — skipped", md5, zf.getinfo(member).file_size)
            continue
        ext = member.rsplit(".", 1)[-1].lower()
        caption = str(photo.get("caption") or "").strip()
        items.append(
            {
                "filename": f"{md5}.{ext}",
                "media_type": "image",
                "data": zf.read(member),
                "caption": caption or None,
                "is_inline": False,
            }
        )
    return items


def parse_dayone_zip(content: bytes) -> list[dict[str, Any]]:
    """Parse a Day One export ZIP into entry dicts (empty on non-Day One ZIP)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content), "r")
    except zipfile.BadZipFile:
        return []

    out: list[dict[str, Any]] = []
    with zf:
        journal = _load_journal(zf)
        if journal is None:
            return out
        photo_index = _photo_index(zf)
        entries = journal.get("entries") or []
        for e in entries:
            date_raw = str(e.get("creationDate", ""))[:10]
            body = (e.get("text") or "").strip()
            media = _media_for_photos(zf, photo_index, e)
            # A photo-only entry is a real entry — only truly empty rows are dropped.
            if not date_raw or (not body and not media):
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
                    "media": media,
                }
            )
    return out
