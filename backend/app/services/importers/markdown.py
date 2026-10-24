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

    for line in frontmatter.split("\n"):
        line = line.strip()
        if line.startswith("date:"):
            entry_date = line.split(":", 1)[1].strip()[:10]
        elif line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("mood:"):
            mood = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("- "):
            # Lines are stripped above, so a YAML list item is "- item" here.
            # (Previously checked "  - " which never matched post-strip, silently
            # dropping all frontmatter tags.)
            tags.append(line[2:].strip())

    return {
        "entry_date": entry_date,
        "title": title,
        "body": body,
        "mood": mood,
        "tags": tags,
    }
