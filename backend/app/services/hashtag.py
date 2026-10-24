"""Body-driven tagging: extract `#hashtags` and resolve them to Tag rows.

Tags "live in the text" — a note/entry's tags are the `#tokens` in its body. The
services call :func:`extract_hashtags` on save and sync the entity's tag links to
exactly that set, so adding/removing a ``#tag`` in the body adds/removes the tag.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag

# A `#` starts a tag only when not preceded by a word/hyphen char, so inline
# `#tag` counts but `foo#bar` and markdown `# heading` (space after #) don't.
_HASHTAG_RE = re.compile(r"(?<![\w-])#([\w-]+)")


def extract_hashtags(body: str | None) -> list[str]:
    """Unique tag names from `#tokens` in the body, in first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _HASHTAG_RE.finditer(body or ""):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


async def resolve_tag_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """Resolve tag names to ids, creating any that don't already exist.

    Returns ids in the same order as ``names`` (caller passes unique names).
    """
    if not names:
        return []
    rows = (await db.execute(select(Tag).where(Tag.name.in_(names)))).scalars().all()
    by_name = {t.name: t.id for t in rows}
    for name in names:
        if name not in by_name:
            tag = Tag(name=name)
            db.add(tag)
            await db.flush()
            by_name[name] = tag.id
    return [by_name[n] for n in names]
