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

    async def export_markdown(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> bytes:
        """Export entries as an Obsidian-compatible Markdown vault bundled inside a ZIP file."""
        import io
        import zipfile
        from sqlalchemy.orm import selectinload
        from app.core.config import settings

        q = (
            select(Entry)
            .where(Entry.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Entry.tag_associations).selectinload(EntryTag.tag),
                selectinload(Entry.media),
            )
            .order_by(Entry.entry_date)
        )

        if start_date:
            q = q.where(Entry.entry_date >= start_date)
        if end_date:
            q = q.where(Entry.entry_date <= end_date)

        result = await self.db.execute(q)
        entries = list(result.scalars().all())

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry in entries:
                # 1. Gather tags
                tags = [assoc.tag.name for assoc in entry.tag_associations if assoc.tag]

                # 2. Gather attachments and copy files to Zip
                attachments_meta = []
                for media in entry.media:
                    local_file_path = settings.MEDIA_DIR / media.storage_path
                    if local_file_path.exists():
                        zip_media_path = f"attachments/{entry.entry_date}/{media.filename}"
                        zip_file.writestr(zip_media_path, local_file_path.read_bytes())
                        attachments_meta.append({
                            "filename": media.filename,
                            "size": media.file_size,
                            "type": media.media_type,
                            "path": zip_media_path,
                        })

                # 3. Create frontmatter manually to avoid PyYAML dependency
                metadata = {
                    "date": str(entry.entry_date),
                    "title": entry.title,
                    "mood": entry.mood,
                    "tags": tags,
                    "location": entry.location_name,
                    "latitude": entry.latitude,
                    "longitude": entry.longitude,
                }
                if attachments_meta:
                    metadata["attachments"] = attachments_meta

                frontmatter_block = self._dump_yaml(metadata)
                
                # 4. Format entry body with relative links
                body_content = entry.body or ""
                
                unread_attachments = []
                for attachment in attachments_meta:
                    if attachment["filename"] not in body_content:
                        unread_attachments.append(attachment)
                
                if unread_attachments:
                    body_content += "\n\n## Attachments\n"
                    for attachment in unread_attachments:
                        rel_path = f"../../attachments/{entry.entry_date}/{attachment['filename']}"
                        if attachment["type"] == "image":
                            body_content += f"![{attachment['filename']}]({rel_path})\n"
                        elif attachment["type"] == "audio":
                            body_content += f'<audio controls src="{rel_path}"></audio>\n'
                        elif attachment["type"] == "video":
                            body_content += f'<video controls src="{rel_path}"></video>\n'
                        else:
                            body_content += f"[{attachment['filename']}]({rel_path})\n"

                full_markdown = f"---\n{frontmatter_block}\n---\n\n{body_content}"

                # 5. Save markdown entry in zip
                year_str = entry.entry_date.strftime("%Y")
                month_str = entry.entry_date.strftime("%m")
                zip_md_path = f"journal/{year_str}/{month_str}/{entry.entry_date}.md"
                zip_file.writestr(zip_md_path, full_markdown.encode("utf-8"))

        return zip_buffer.getvalue()

    @staticmethod
    def _dump_yaml(data: dict) -> str:
        """Helper to serialize a simple dictionary to YAML format manually."""
        lines = []
        for k, v in data.items():
            if v is None:
                lines.append(f"{k}: null")
            elif isinstance(v, (bool, int, float)):
                lines.append(f"{k}: {str(v).lower() if isinstance(v, bool) else str(v)}")
            elif isinstance(v, str):
                if ":" in v or "'" in v or '"' in v or "\n" in v or "-" in v:
                    escaped = v.replace('"', '\\"')
                    lines.append(f'{k}: "{escaped}"')
                else:
                    lines.append(f"{k}: {v}")
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{k}: []")
                else:
                    lines.append(f"{k}:")
                    for item in v:
                        if isinstance(item, dict):
                            lines.append(f"  - filename: {item.get('filename')}")
                            lines.append(f"    size: {item.get('size')}")
                            lines.append(f"    type: {item.get('type')}")
                            lines.append(f"    path: {item.get('path')}")
                        else:
                            lines.append(f"  - {item}")
        return "\n".join(lines)
