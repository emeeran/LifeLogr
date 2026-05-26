"""ExportService — PDF and HTML export with branded templates."""

from __future__ import annotations

from datetime import date

from fpdf import FPDF
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


class _DiaryPDF(FPDF):
    """Custom PDF with Georgia-like font and branded styling."""

    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=25)

    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, "Diarilinux Export", align="C")
            self.ln(5)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._md = MarkdownIt()

    async def _get_entries(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[Entry]:
        q = (
            select(Entry)
            .where(Entry.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
            )
            .order_by(Entry.entry_date)
        )

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
                tag_html = f"<div>{tag_html}</div>"

            body_html = self._md.render(entry.body)
            parts.append(
                _ENTRY_HTML.format(
                    date=entry.entry_date,
                    title=title_part,
                    mood=mood_part,
                    tags=tag_html,
                    body_html=body_html,
                )
            )

        content = "\n".join(parts)
        return _HTML_TEMPLATE.format(title="Diarilinux Export", content=content)

    async def export_pdf(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> bytes:
        """Export entries as a PDF document using fpdf2 (pure Python, no system deps)."""
        entries = await self._get_entries(start_date, end_date)

        pdf = _DiaryPDF()
        pdf.alias_nb_pages()

        for i, entry in enumerate(entries):
            pdf.add_page()

            # Title line: date + optional title
            title_text = f"{entry.entry_date}"
            if entry.title:
                title_text += f"  —  {entry.title}"

            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(44, 62, 80)  # #2c3e50
            pdf.cell(0, 12, title_text, new_x="LMARGIN", new_y="NEXT")

            # Blue divider line
            pdf.set_draw_color(52, 152, 219)  # #3498db
            pdf.set_line_width(0.8)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

            # Meta: mood + tags
            meta_parts: list[str] = []
            if entry.mood:
                meta_parts.append(f"Mood: {entry.mood}")
            tags = [a.tag.name for a in entry.tag_associations if a.tag]
            if tags:
                meta_parts.append(f"Tags: {', '.join(tags)}")

            if meta_parts:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(102, 102, 102)  # #666
                pdf.cell(0, 6, "  |  ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)

            # Body — strip markdown to plain text for PDF
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(51, 51, 51)  # #333
            body_text = self._md.render(entry.body)
            # Quick HTML→text: remove tags
            import re

            plain = re.sub(r"<[^>]+>", "", body_text)
            plain = plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            plain = plain.replace("&#39;", "'").replace("&quot;", '"')
            pdf.multi_cell(0, 6, plain)

        return bytes(pdf.output())
