"""Synthetic Day One export ZIP builder for tests.

Mirrors ``diarium_diary.py``: builds a tiny in-memory export with the real
Day One shape — ``Journal.json`` with an ``entries`` array plus ``photos/``
members keyed by md5 — so suites never need a real personal export.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

# Minimal PNG (1×1) — passes the media pipeline's magic-byte signature check.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0f01f0005000105ab5e30"
    "5f0000000049454e44ae426082"
)


def photo_bytes(data: bytes = PNG_1X1) -> tuple[str, bytes]:
    """Return ``(md5, data)`` for photo content, as Day One keys them."""
    return hashlib.md5(data, usedforsecurity=False).hexdigest(), data


def build_dayone_zip(entries: list[dict[str, Any]], photos: dict[str, bytes] | None = None) -> bytes:
    """Build a Day One export ZIP.

    *entries* are raw Day One entry dicts (``creationDate``, ``text``, …).
    *photos* maps ``md5`` -> image bytes; each is written as
    ``photos/<md5>.png``. Pass ``{}`` to produce entries whose photo
    references resolve to nothing.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Journal.json", json.dumps({"entries": entries}))
        for md5, data in (photos or {}).items():
            zf.writestr(f"photos/{md5}.png", data)
    return buf.getvalue()
