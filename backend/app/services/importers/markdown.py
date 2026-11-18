"""Parser for markdown-with-YAML-frontmatter entry files.

Extracted from ``app.routers.entries``. Pure function: raw markdown text in,
our import-shaped dict (or ``None`` if empty) out.
"""

from __future__ import annotations

from typing import Any


def parse_markdown_entry(raw: str) -> dict[str, Any] | None:
    """Parse a markdown file with YAML frontmatter into an import dict."""

    if not raw.startswith("---"):
        # No frontmatter — try to extract date from filename later
        body = raw.strip()
        if not body:
            return None
        return {"entry_date": "", "title": None, "body": body, "mood": None, "tags": []}

    # Extract frontmatter
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()
    body = parts[2].strip()
    if not body:
        return None

    entry_date = ""
    title = None
    mood = None
    tags: list[str] = []
    media: list[dict[str, Any]] = []
    # Which top-level key the "- " list items currently belong to — without
    # this, the `media:` manifest's items would be swallowed as tags.
    section: str | None = None
    current_media: dict[str, Any] | None = None

    for line in frontmatter.split("\n"):
        stripped = line.strip()
        if stripped == "tags:":
            section = "tags"
            continue
        if stripped == "media:":
            section = "media"
            continue
        if line.startswith("  - ") or line.startswith("- "):
            item = stripped[2:].strip()
            if section == "media":
                # "  - ref: 42" opens a media item; follow-up "    key: v"
                # lines below fill it in.
                current_media = {}
                if ":" in item:
                    k, _, v = item.partition(":")
                    current_media[k.strip()] = v.strip()
                media.append(current_media)
            else:
                # (Previously checked "  - " which never matched post-strip,
                # silently dropping all frontmatter tags.)
                tags.append(item)
            continue
        if line.startswith("    ") and section == "media" and current_media is not None:
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                current_media[k.strip()] = v.strip()
            continue
        # Any non-list line ends the current list section.
        section = None
        current_media = None
        if stripped.startswith("date:"):
            entry_date = stripped.split(":", 1)[1].strip()[:10]
        elif stripped.startswith("title:"):
            title = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.startswith("mood:"):
            mood = stripped.split(":", 1)[1].strip().strip('"')

    return {
        "entry_date": entry_date,
        "title": title,
        "body": body,
        "mood": mood,
        "tags": tags,
        "media": media,
    }
