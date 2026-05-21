"""ExportService — PDF and HTML export with branded templates."""
from __future__ import annotations

from datetime import date

from markdown_it import MarkdownIt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entry import Entry
from app.models.tag import EntryTag


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 800px; margin: 40px auto; color: #333; }}
  h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 16px; }}
  .tag {{ background: #e8f4f8; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }}
  .entry {{ margin-bottom: 40px; page-break-after: always; }}
  .mood {{ color: #e67e22; font-weight: bold; }}
  @page {{ margin: 2cm; }}
</style>
</head>
<body>
{content}
</body>
</html>"""

_ENTRY_HTML = """
<div class="entry">
  <h1>{date}{title}</h1>
  <div class="meta">
    {mood}{tags}
  </div>
  <div class="body">{body_html}</div>
</div>
"""


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._md = MarkdownIt()

    async def _get_entries(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[Entry]:
        q = select(Entry).where(Entry.is_deleted == False).options(  # noqa: E712
            selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
        ).order_by(Entry.entry_date)

        if start_date:
            q = q.where(Entry.entry_date >= start_date)
        if end_date:
            q = q.where(Entry.entry_date <= end_date)

        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def export_html(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> str:
        """Export entries as a single styled HTML document."""
        entries = await self._get_entries(start_date, end_date)
        parts = []
        for entry in entries:
            tags = [a.tag.name for a in entry.tag_associations if a.tag]
            title_part = f" — {entry.title}" if entry.title else ""
            mood_part = f'<span class="mood">{entry.mood}</span> · ' if entry.mood else ""
            tag_html = " ".join(f'<span class="tag">{t}</span>' for t in tags)
            if tag_html:
                tag_html = f'<div>{tag_html}</div>'

            body_html = self._md.render(entry.body)
            parts.append(_ENTRY_HTML.format(
                date=entry.entry_date,
                title=title_part,
                mood=mood_part,
                tags=tag_html,
                body_html=body_html,
            ))

        content = "\n".join(parts)
        return _HTML_TEMPLATE.format(title="Diarilinux Export", content=content)

    async def export_pdf(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> bytes:
        """Export entries as a PDF document."""
        from weasyprint import HTML

        html_content = await self.export_html(start_date, end_date)
        pdf = HTML(string=html_content).write_pdf()
        return pdf
