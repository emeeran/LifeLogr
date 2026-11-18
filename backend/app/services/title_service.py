"""Title derivation for the "fill missing titles" backfill.

Mirror of `frontend/src/utils/autoTitle.ts`. Kept in step deliberately: the
editor derives on save, and this backfills rows saved before that existed. Any
behaviour change must land in both (and in both test suites) — otherwise a
backfill would produce titles the editor would never choose.
"""

from __future__ import annotations

import re

_MAX_DEFAULT = 120

_HEADING_RE = re.compile(r"^#{1,6}\s+")
_QUOTE_RE = re.compile(r"^>\s?")
_LIST_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_MARKUP_RE = re.compile(r"[*_~`]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_PUNCT_RE = re.compile(r"[\s.;:,!?\-\u2013\u2014]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def _truncate(value: str, max_length: int) -> str:
    chars = list(value)
    if len(chars) <= max_length:
        return value
    cut = "".join(chars[:max_length])
    space = cut.rfind(" ")
    base = cut[:space] if space > max_length * 0.6 else cut
    return f"{base.rstrip()}\u2026"


def derive_title(body: str | None, max_length: int = _MAX_DEFAULT) -> str:
    """First line of *body* that carries text once markdown is stripped.

    Returns ``""`` for bodies with no text (photo-only entries), which the
    caller must treat as "leave untitled".
    """
    if not body:
        return ""

    for raw in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue

        line = _HEADING_RE.sub("", line)
        line = _QUOTE_RE.sub("", line)
        line = _LIST_RE.sub("", line)
        # Images and links keep their human-readable label; a bare image with
        # no alt text contributes nothing and falls through to the next line.
        line = _IMAGE_RE.sub(r"\1", line)
        line = _LINK_RE.sub(r"\1", line)
        line = _INLINE_MARKUP_RE.sub("", line)
        line = _HTML_TAG_RE.sub("", line)
        line = _WHITESPACE_RE.sub(" ", line).strip()
        line = _TRAILING_PUNCT_RE.sub("", line).strip()

        if line:
            return _truncate(line, max_length)
    return ""
