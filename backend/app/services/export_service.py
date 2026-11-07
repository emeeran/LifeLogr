"""ExportService — PDF and HTML export with branded templates."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date

from markdown_it import MarkdownIt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from typing import Any

from app.core.jobs import ProgressReporter, noop_reporter
from app.models.entry import Entry
from app.models.tag import EntryTag

logger = logging.getLogger(__name__)

# One sentence, surfaced in every plain-text export format (Markdown frontmatter,
# HTML banner, PDF line) for entries whose body/attachments stay ciphertext.
ENCRYPTED_NOTE_TEXT = "Attachments of this encrypted entry are omitted from exports."


def _skip_encrypted_media(entry: Entry, media: Any, fmt: str) -> None:
    """Log one skipped attachment of an encrypted entry (media never exports).

    The entry's body is passphrase-encrypted, so an export can never contain a
    coherent decrypted document for it — and decrypting the attachment into a
    plaintext export file would leak exactly the content the user hid.
    """

    logger.info(
        "Skipping attachment %s of encrypted entry %s in %s export",
        media.storage_path,
        entry.id,
        fmt,
    )

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
  .gallery {{ margin-top: 12px; }}
  .gallery img, .gallery video {{ max-width: 100%; border-radius: 4px; }}
  .gallery figcaption {{ color: #666; font-size: 0.8em; }}
  .encrypted-note {{ color: #8a6d3b; background: #fcf8e3; border: 1px solid #faebcc;
    padding: 6px 10px; border-radius: 4px; margin-bottom: 12px; font-size: 0.9em; }}
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
  <div class="body">{body_html}</div>{gallery}
</div>
"""

# Gallery blocks for attachments not already referenced in the body. Paths are
# relative to website/index.html inside the HTML export ZIP.
_FIGURE_HTML = {
    "image": '<figure><img src="{src}" alt="{name}"><figcaption>{name}</figcaption></figure>',
    "audio": '<figure><audio controls src="{src}"></audio><figcaption>{name}</figcaption></figure>',
    "video": '<figure><video controls src="{src}"></video><figcaption>{name}</figcaption></figure>',
    "document": '<figure><a href="{src}">{name}</a></figure>',
}


# fpdf2's built-in core fonts render the Latin-1 (ISO-8859-1) range only, so map
# common Unicode punctuation (em/en dash, smart quotes, ellipsis, …) to ASCII and
# clip anything else outside Latin-1 — otherwise PDF export raises
# FPDFUnicodeEncodingException on entries containing those characters.
_PDF_TEXT_REPLACEMENTS = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "…": "...",  # ellipsis
    "•": "*",  # bullet
    " ": " ",  # non-breaking space
    "™": "(TM)",
    "®": "(R)",
}


def _pdf_text(text: str) -> str:
    """Coerce text into the Latin-1 range fpdf2's core fonts can render."""
    for src, dst in _PDF_TEXT_REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Replace any remaining non-Latin-1 code points (e.g. CJK, emoji) with "?".
    return text.encode("latin-1", "replace").decode("latin-1")


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Raw HTML in entry bodies must NEVER pass through into the export
        # document: MarkdownIt's default preset renders ``<script>`` verbatim,
        # which turns a stored XSS payload in one entry into an executable
        # script in every exported HTML file. ``html: False`` escapes it.
        self._md = MarkdownIt("default", {"html": False})

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

    def _entry_fragment(self, entry: Entry, body_html: str, gallery_html: str = "") -> str:
        """Render one entry as the shared HTML fragment (single-file + ZIP exports)."""
        tags = [a.tag.name for a in entry.tag_associations if a.tag]
        title_part = f" — {html.escape(entry.title)}" if entry.title else ""
        mood_part = (
            f'<span class="mood">{html.escape(entry.mood)}</span> · ' if entry.mood else ""
        )
        tag_html = " ".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
        if tag_html:
            tag_html = f"<div>{tag_html}</div>"
        # Mirrors the Markdown export's frontmatter `attachments_note`: the body
        # stays ciphertext and attachments are omitted, so say so in the document.
        note_part = (
            f'<div class="encrypted-note">{ENCRYPTED_NOTE_TEXT}</div>'
            if entry.is_encrypted
            else ""
        )
        return _ENTRY_HTML.format(
            date=html.escape(str(entry.entry_date)),
            title=title_part,
            mood=mood_part,
            tags=tag_html + note_part,
            body_html=body_html,
            gallery=gallery_html,
        )

    async def export_html(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> str:
        """Export entries as a single styled HTML document."""
        entries = await self._get_entries(start_date, end_date)
        parts = [
            self._entry_fragment(entry, self._md.render(entry.body)) for entry in entries
        ]

        content = "\n".join(parts)
        return _HTML_TEMPLATE.format(title=html.escape("LifeLogr Export"), content=content)

    async def export_html_zip(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        report: ProgressReporter = noop_reporter,
    ) -> bytes:
        """Export entries as an HTML archive ZIP with media attachments.

        ``website/index.html`` holds every entry (same styling as
        :meth:`export_html`); attachments are copied to
        ``attachments/<date>/<filename>`` and referenced relatively from the
        page, mirroring the Markdown vault ZIP. Attachments not already
        referenced by the body render as a figure gallery under the entry.
        """
        from sqlalchemy.orm import selectinload

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

        # Zip assembly reads every attachment from disk — off the event loop,
        # same as the Markdown vault path.
        return await asyncio.to_thread(self._build_html_zip, entries, report)

    def _build_html_zip(self, entries: list[Entry], report: ProgressReporter = noop_reporter) -> bytes:
        """Synchronously assemble the HTML archive ZIP for ``entries``.

        Same-day entries sharing an attachment filename would silently
        overwrite each other (the Markdown vault path has this latent issue) —
        later collisions get an ``<id>-`` prefix instead.
        """
        import io
        import zipfile

        from app.core.config import settings

        zip_buffer = io.BytesIO()
        used_attachment_paths: set[str] = set()
        parts: list[str] = []
        attachment_total = sum(
            1
            for e in entries
            if not e.is_encrypted
            for m in e.media
            if (settings.MEDIA_DIR / m.storage_path).exists()
        )
        attachment_done = 0
        if report is not None:
            report("render", 0, len(entries))
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry_index, entry in enumerate(entries):
                body = entry.body or ""
                body_html = self._md.render(body)
                gallery_parts: list[str] = []
                for media in entry.media:
                    if entry.is_encrypted:
                        # Attachments of an encrypted entry never leave the app:
                        # decrypting them into a plaintext export would leak the
                        # very files the user hid, and their text stays ciphertext
                        # anyway (export cannot hold the passphrase key).
                        _skip_encrypted_media(entry, media, "html")
                        continue
                    local_file_path = settings.MEDIA_DIR / media.storage_path
                    if not local_file_path.exists():
                        continue
                    zip_media_path = f"attachments/{entry.entry_date}/{media.filename}"
                    if zip_media_path in used_attachment_paths:
                        zip_media_path = (
                            f"attachments/{entry.entry_date}/{media.id}-{media.filename}"
                        )
                    used_attachment_paths.add(zip_media_path)
                    zip_file.writestr(zip_media_path, local_file_path.read_bytes())
                    attachment_done += 1
                    if report is not None:
                        report("attachments", attachment_done, attachment_total)

                    # Skip the gallery for media the body already references
                    # (by filename or by its API URL).
                    if media.filename and media.filename in body:
                        continue
                    if f"/api/v1/media/{media.id}/" in body:
                        continue
                    template = _FIGURE_HTML.get(media.media_type, _FIGURE_HTML["document"])
                    gallery_parts.append(
                        template.format(
                            src=f"../{zip_media_path}", name=html.escape(media.filename or "attachment")
                        )
                    )

                gallery_html = (
                    "\n  <div class=\"gallery\">" + "".join(gallery_parts) + "</div>"
                    if gallery_parts
                    else ""
                )
                parts.append(
                    self._entry_fragment(entry, body_html, gallery_html)
                )
                if report is not None:
                    report("render", entry_index + 1, len(entries))

            content = "\n".join(parts)
            page = _HTML_TEMPLATE.format(title=html.escape("LifeLogr Export"), content=content)
            zip_file.writestr("website/index.html", page.encode("utf-8"))
        return zip_buffer.getvalue()

    async def export_pdf(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> bytes:
        """Export entries as a PDF document using fpdf2 (pure Python, no system deps).

        fpdf2 (and its transitive numpy/PIL via ``image_parsing``) is imported lazily
        here so it doesn't inflate app startup — PDF export is a rarely-used feature.
        Matches the lazy-import pattern in the ocr/tts/recording services.
        """
        entries = await self._get_entries(start_date, end_date)
        # Rendering is pure CPU (fpdf2 layout + markdown parse per entry) — offload
        # it from the event loop so a large journal doesn't stall other requests.
        return await asyncio.to_thread(self._render_pdf, entries)

    def _render_pdf(self, entries: list[Entry]) -> bytes:
        """Synchronously lay out ``entries`` into the branded PDF."""
        from fpdf import FPDF

        class _DiaryPDF(FPDF):
            """Custom PDF with Georgia-like font and branded styling."""

            def __init__(self) -> None:
                super().__init__()
                self.set_auto_page_break(auto=True, margin=25)

            def header(self) -> None:
                if self.page_no() > 1:
                    self.set_font("Helvetica", "I", 8)
                    self.set_text_color(150, 150, 150)
                    self.cell(0, 10, "LifeLogr Export", align="C")
                    self.ln(5)

            def footer(self) -> None:
                self.set_y(-15)
                self.set_font("Helvetica", "I", 8)
                self.set_text_color(150, 150, 150)
                self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

        pdf = _DiaryPDF()
        pdf.alias_nb_pages()

        for entry in entries:
            pdf.add_page()

            # Title line: date + optional title
            title_text = f"{entry.entry_date}"
            if entry.title:
                title_text += f"  —  {entry.title}"

            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(44, 62, 80)  # #2c3e50
            pdf.cell(0, 12, _pdf_text(title_text), new_x="LMARGIN", new_y="NEXT")

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
                pdf.cell(0, 6, _pdf_text("  |  ".join(meta_parts)), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)

            if entry.is_encrypted:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(138, 109, 59)  # #8a6d3b
                pdf.multi_cell(0, 6, _pdf_text(ENCRYPTED_NOTE_TEXT))
                pdf.ln(4)

            # Body — strip markdown to plain text for PDF
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(51, 51, 51)  # #333
            body_text = self._md.render(entry.body)
            # Quick HTML→text: remove tags
            plain = re.sub(r"<[^>]+>", "", body_text)
            plain = html.unescape(plain)
            pdf.multi_cell(0, 6, _pdf_text(plain))

        return bytes(pdf.output())

    async def export_markdown(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> bytes:
        """Export entries as an Obsidian-compatible Markdown vault bundled inside a ZIP file."""
        from sqlalchemy.orm import selectinload

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

        # Zip assembly reads every attachment from disk and deflate-compresses it
        # (plus markdown per entry) — CPU + blocking file I/O, so offload it.
        return await asyncio.to_thread(self._build_markdown_zip, entries)

    def _build_markdown_zip(self, entries: list[Entry]) -> bytes:
        """Synchronously assemble the Obsidian vault ZIP for ``entries``.

        Multiple entries can share one ``entry_date``, so the naive
        ``journal/Y/M/<date>.md`` path silently overwrote every entry after the
        first for that day (data loss in the export). The first entry of a date
        keeps the legacy path; any further same-day entry gets ``<date>-<id>.md``.
        """
        import io
        import zipfile

        from app.core.config import settings

        zip_buffer = io.BytesIO()
        used_paths: set[str] = set()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry in entries:
                # 1. Gather tags
                tags = [assoc.tag.name for assoc in entry.tag_associations if assoc.tag]

                # 2. Gather attachments and copy files to Zip
                attachments_meta: list[dict[str, object]] = []
                for media in entry.media:
                    if entry.is_encrypted:
                        # Same rule as the HTML export: attachments of an
                        # encrypted entry never leave the app in the clear;
                        # the frontmatter records the omission.
                        _skip_encrypted_media(entry, media, "markdown")
                        continue
                    local_file_path = settings.MEDIA_DIR / media.storage_path
                    if local_file_path.exists():
                        zip_media_path = f"attachments/{entry.entry_date}/{media.filename}"
                        zip_file.writestr(zip_media_path, local_file_path.read_bytes())
                        attachments_meta.append(
                            {
                                "filename": media.filename,
                                "size": media.file_size,
                                "type": media.media_type,
                                "path": zip_media_path,
                            }
                        )

                # 3. Create frontmatter manually to avoid PyYAML dependency
                metadata: dict[str, object] = {
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
                if entry.is_encrypted:
                    metadata["attachments_note"] = ENCRYPTED_NOTE_TEXT

                frontmatter_block = self._dump_yaml(metadata)

                # 4. Format entry body with relative links
                body_content = entry.body or ""

                unread_attachments: list[dict[str, object]] = []
                for attachment in attachments_meta:
                    filename = str(attachment.get("filename", ""))
                    if filename and filename not in body_content:
                        unread_attachments.append(attachment)

                if unread_attachments:
                    body_content += "\n\n## Attachments\n"
                    for attachment in unread_attachments:
                        filename = str(attachment.get("filename", "attachment"))
                        media_type = str(attachment.get("type", "document"))
                        rel_path = f"../../attachments/{entry.entry_date}/{filename}"
                        if media_type == "image":
                            body_content += f"![{filename}]({rel_path})\n"
                        elif media_type == "audio":
                            body_content += f'<audio controls src="{rel_path}"></audio>\n'
                        elif media_type == "video":
                            body_content += f'<video controls src="{rel_path}"></video>\n'
                        else:
                            body_content += f"[{filename}]({rel_path})\n"

                full_markdown = f"---\n{frontmatter_block}\n---\n\n{body_content}"

                # 5. Save markdown entry in the zip under a collision-free path.
                year_str = entry.entry_date.strftime("%Y")
                month_str = entry.entry_date.strftime("%m")
                zip_md_path = f"journal/{year_str}/{month_str}/{entry.entry_date}.md"
                if zip_md_path in used_paths:
                    zip_md_path = f"journal/{year_str}/{month_str}/{entry.entry_date}-{entry.id}.md"
                used_paths.add(zip_md_path)
                zip_file.writestr(zip_md_path, full_markdown.encode("utf-8"))

        return zip_buffer.getvalue()

    @staticmethod
    def _dump_yaml(data: dict[str, object]) -> str:
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


# ── Diarium-native .diary SQLite export ─────────────────────────────────────
# Moved from app.routers.entries so the router stays a thin transport layer.
# Produces the real Diarium schema so Diarium's backup-restore accepts the file.
#
# The DDL below is the verbatim schema extracted from the shipped Diarium
# 3.3.12.0 binary (UTF-16 strings in Diarium.exe, SHA-256 5b8cc6fb…): its own
# database is created from exactly these CREATE TABLE statements, and entries
# are written with `INSERT OR REPLACE INTO Entries(DiaryEntryId,Heading,Text,
# Rating,Latitude,Longitude)`. Do not "simplify" it — Latitude/Longitude and
# Tags.Type are NOT NULL in the real schema, and a backup missing any of the
# six tables is not a valid Diarium database.
#
# Conventions verified from the same binary and the vendor's documented
# behaviour:
# - DiaryEntryId is .NET DateTime ticks (100ns since 0001-01-01) — it *is* the
#   entry's timestamp; the UI derives the date from it.
# - Text is HTML, typically a sequence of <p>…</p> paragraphs.
# - Rating is 1–5 (awful/bad/meh/good/rad), 0 = unrated.
# - Tags.Type: 0 = tag, 1 = person, 2 = tracker.
_DOTNET_TICKS_EPOCH = 621355968000000000
_TICKS_PER_SECOND = 10_000_000
_MOOD_TO_RATING = {"awful": 1, "bad": 2, "meh": 3, "good": 4, "great": 5}
# Media.Type: 0 image, 1 audio, 2 unknown, 3 document, 4 audio/video attachment.
_DIARIUM_MEDIA_TYPE = {"image": 0, "audio": 1, "document": 3, "video": 4}
_DIARIUM_DDL = """CREATE TABLE Entries(DiaryEntryId bigint primary key not null, Heading varchar not null, Text varchar not null, Rating integer not null, Latitude float not null, Longitude float not null);
CREATE TABLE EntryTags(DiaryEntryId bigint not null, DiaryTagId integer not null, TrackingValue varchar);
CREATE TABLE Events(DiaryEventId integer primary key autoincrement not null, Type integer not null, Content varchar not null, Tag varchar, DiaryEntryId bigint not null );
CREATE TABLE Media(DiaryMediaId varchar(36) primary key not null, Type integer not null, Data blob, Name varchar not null, FileEnding varchar not null, "Index" integer not null, DiaryEntryId bigint not null);
CREATE TABLE Tags(DiaryTagId integer primary key autoincrement not null, Value varchar not null, Type integer not null, Color varchar, Icon varchar);
CREATE TABLE Templates(TemplateId integer primary key autoincrement not null, Name varchar not null, Heading varchar not null, Text varchar not null, Tags varchar not null);
"""


def _markdown_to_diarium_html(body: str) -> str:
    """Convert a markdown/plain-text body into Diarium-style HTML.

    Diarium stores entry text as HTML (<p>...</p> with <br> line breaks) — the
    inverse of the HTML-stripping performed by the .diary importer.
    """
    escaped = html.escape(body or "")
    paragraphs = re.split(r"\n\s*\n", escaped)
    rendered = []
    for para in paragraphs:
        if not para.strip():
            continue
        para = para.replace("\n", "<br>")
        rendered.append(f"<p>{para}</p>")
    return "".join(rendered)


async def build_diarium_database(
    entries: list[Entry], report: ProgressReporter = noop_reporter
) -> bytes:
    """Build a Diarium-native .diary SQLite database (as bytes) from entries.

    ``entries`` must have ``tag_associations`` loaded (selectinload). Returns the
    serialized SQLite file so the caller can wrap it in a StreamingResponse.
    The SQLite build is CPU-bound, so it runs in a worker thread.
    """
    return await asyncio.to_thread(_build_diarium_database_sync, entries, report)


def _build_diarium_database_sync(
    entries: list[Entry], report: ProgressReporter = noop_reporter
) -> bytes:
    """Synchronously serialize ``entries`` into the Diarium SQLite schema."""
    import sqlite3
    import tempfile
    from datetime import date as date_type
    from datetime import datetime, timezone
    from pathlib import Path

    from app.core.config import settings

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_DIARIUM_DDL)

        tag_id_map: dict[str, int] = {}
        used_entry_ids: set[int] = set()

        media_total = sum(
            1
            for e in entries
            if not e.is_encrypted
            for m in e.media
            if (settings.MEDIA_DIR / m.storage_path).is_file()
        )
        media_done = 0
        if report is not None:
            report("render", 0, len(entries))

        for entry_index, entry in enumerate(entries):
            ed = entry.entry_date
            if isinstance(ed, str):
                ed = date_type.fromisoformat(ed[:10])
            # DiaryEntryId = .NET ticks for the entry date at 00:00:00 UTC.
            midnight = datetime.combine(ed, datetime.min.time(), tzinfo=timezone.utc)
            unix_us = int(midnight.timestamp() * 1_000_000)
            entry_id = _DOTNET_TICKS_EPOCH + unix_us * 10
            # Guarantee uniqueness while staying on the same calendar day.
            while entry_id in used_entry_ids:
                entry_id += _TICKS_PER_SECOND
            used_entry_ids.add(entry_id)

            heading = (entry.title or "").strip()
            text_html = _markdown_to_diarium_html(entry.body or "")
            rating = _MOOD_TO_RATING.get(entry.mood or "", 0)

            conn.execute(
                "INSERT INTO Entries (DiaryEntryId, Heading, Text, Rating, Latitude, Longitude) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    heading,
                    text_html,
                    rating,
                    # NOT NULL in the real schema — unrated location reads as 0.
                    float(entry.latitude or 0.0),
                    float(entry.longitude or 0.0),
                ),
            )
            for assoc in entry.tag_associations:
                tag = assoc.tag
                if not tag or not tag.name:
                    continue
                if tag.name not in tag_id_map:
                    cur = conn.execute(
                        # Type 0 = tag, 2 = tracker (1 is person — lifelogr has
                        # no separate person kind). Tracker readings ride in
                        # EntryTags.TrackingValue. Color/Icon stay NULL.
                        "INSERT INTO Tags (Value, Type, Color, Icon) VALUES (?, ?, NULL, NULL)",
                        (tag.name, 2 if getattr(tag, "is_tracker", False) else 0),
                    )
                    tag_id_map[tag.name] = cur.lastrowid  # type: ignore[assignment]
                conn.execute(
                    "INSERT OR IGNORE INTO EntryTags (DiaryEntryId, DiaryTagId, TrackingValue) "
                    "VALUES (?, ?, ?)",
                    (entry_id, tag_id_map[tag.name], assoc.tracking_value),
                )

            # Media attachments as real Media rows (blob + name parts + order),
            # so Diarium shows them after a restore. Name/FileEnding split the
            # filename the way Diarium stores it (e.g. IMG_3631 / .jpg).
            from uuid import uuid4

            for media_index, media in enumerate(entry.media):
                if entry.is_encrypted:
                    # Attachments of an encrypted entry stay in the app (same
                    # rule as the HTML/markdown exports).
                    _skip_encrypted_media(entry, media, "diarium")
                    continue
                src = settings.MEDIA_DIR / media.storage_path
                if not src.is_file():
                    logger.warning(
                        "Media file missing on disk, skipped in .diary export: %s",
                        media.storage_path,
                    )
                    continue
                stem, dot, ext = media.filename.rpartition(".")
                conn.execute(
                    'INSERT INTO Media (DiaryMediaId, Type, Data, Name, FileEnding, "Index", '
                    "DiaryEntryId) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        _DIARIUM_MEDIA_TYPE.get((media.media_type or "").lower(), 3),
                        src.read_bytes(),
                        stem or media.filename,
                        f".{ext}" if dot else "",
                        media_index,
                        entry_id,
                    ),
                )
                media_done += 1
                if report is not None:
                    report("media", media_done, media_total)
            if report is not None:
                report("render", entry_index + 1, len(entries))

            # Events round-trip back into Diarium's native Events table:
            # weather → Type 0 (the one verified enum value); an imported
            # unknown:<n> kind keeps its original vendor Type so a re-import
            # classifies it identically. Anything unparseable stays 0-shaped
            # but lossless via Tag/Content.
            for event in entry.events:
                kind = event.kind or ""
                if kind.startswith("unknown:"):
                    try:
                        event_type = int(kind.split(":", 1)[1])
                    except ValueError:
                        event_type = 0
                else:
                    event_type = 0
                conn.execute(
                    "INSERT INTO Events (Type, Content, Tag, DiaryEntryId) "
                    "VALUES (?, ?, ?, ?)",
                    (event_type, event.content, event.label, entry_id),
                )
        conn.commit()
        # Match a real Diarium backup's container (format analysis §1):
        # user_version 4. The backup() target file is rollback-journal
        # ("delete") by construction, and sqlite_sequence is maintained by
        # AUTOINCREMENT itself — no manual upkeep needed.
        conn.execute("PRAGMA user_version = 4")
        # Serialize to a binary SQLite file. conn.serialize()/iterdump() aren't
        # available under pysqlite3 (the frozen-build FTS5 swap), so backup() to
        # a file connection (works in both stdlib sqlite3 and pysqlite3).
        tmp = tempfile.NamedTemporaryFile(suffix=".diary", delete=False)
        tmp.close()
        try:
            with sqlite3.connect(tmp.name) as out:
                conn.backup(out)
            return Path(tmp.name).read_bytes()
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    finally:
        conn.close()


# ── Day One JSON export (Diarium's attachment-capable migration import) ─────
# Diarium has no generic JSON import: "Migrate from other app" reads the formats
# of the apps it lists, and its developer points scripted imports at Day One
# explicitly because it is the only one carrying attachments. The JSON names
# each file by md5 and Diarium copies the archive members whose filenames start
# with that value, so media are written as ``photos/<md5>.<ext>``.
#
# Entries are stamped at noon UTC: LifeLogr stores a date, not a time, and noon
# cannot roll into the previous/next day when Diarium converts to local time.
_DAYONE_TIME = "T12:00:00Z"
_DAYONE_TIMEZONE = "UTC"
# Day One names the container by media kind, not by MIME type.
_DAYONE_TYPE_BY_EXT = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "gif": "gif",
    "heic": "heic",
    "webp": "webp",
    "tif": "tiff",
    "tiff": "tiff",
    "mp4": "mp4",
    "mov": "mov",
    "m4v": "mp4",
    "m4a": "m4a",
    "mp3": "mp3",
    "wav": "wav",
    "ogg": "ogg",
    "opus": "opus",
    "pdf": "pdf",
}
_DAYONE_TYPE_BY_MEDIA = {"image": "jpeg", "audio": "mp3", "video": "mp4", "document": "pdf"}


def _dayone_photo_type(media: Any) -> tuple[str, str]:
    """Return ``(extension, dayone_type)`` for one media row."""
    filename = media.filename or ""
    _, dot, ext = filename.rpartition(".")
    ext = ext.lower() if dot and ext else ""
    kind = (media.media_type or "").lower()
    if not ext:
        ext = {"image": "jpg", "audio": "mp3", "video": "mp4", "document": "pdf"}.get(
            kind, "bin"
        )
    return ext, _DAYONE_TYPE_BY_EXT.get(ext, _DAYONE_TYPE_BY_MEDIA.get(kind, ext))


async def build_dayone_zip(
    entries: list[Entry], report: ProgressReporter = noop_reporter
) -> bytes:
    """Build a Day One JSON export ZIP (as bytes) for Diarium's migration import.

    ``entries`` must have ``tag_associations`` and ``media`` loaded. Diarium
    imports this via Settings → Migrate from other app → Day One, which **adds**
    entries and skips any whose date/time already exists — so a repeated push
    is safe, if wasteful. Encrypted entries are skipped (their body is
    ciphertext) and counted in ``Journal.json``'s metadata.
    """
    return await asyncio.to_thread(_build_dayone_zip_sync, entries, report)


def _build_dayone_zip_sync(
    entries: list[Entry], report: ProgressReporter = noop_reporter
) -> bytes:
    import hashlib
    import io
    import json
    import zipfile
    from uuid import NAMESPACE_URL, uuid5

    from app.core.config import settings

    media_total = sum(
        1
        for e in entries
        if not e.is_encrypted
        for m in e.media
        if (settings.MEDIA_DIR / m.storage_path).is_file()
    )
    media_done = 0
    skipped_encrypted = 0
    written_media: set[str] = set()
    items: list[dict[str, Any]] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, entry in enumerate(entries):
            if entry.is_encrypted:
                skipped_encrypted += 1
                continue

            tags = [
                assoc.tag.name
                for assoc in entry.tag_associations
                if getattr(assoc, "tag", None) is not None and assoc.tag.name
            ]
            # Stable per-entry UUID: re-exporting the same journal produces the
            # same identifiers, so a client can recognise entries it has seen.
            item: dict[str, Any] = {
                "uuid": str(uuid5(NAMESPACE_URL, f"lifelogr:entry:{entry.id}")),
                "text": entry.body or "",
                "creationDate": f"{entry.entry_date.isoformat()}{_DAYONE_TIME}",
                "timeZone": _DAYONE_TIMEZONE,
                "starred": False,
                "tags": sorted(tags),
            }
            if entry.title:
                item["title"] = entry.title
            if entry.latitude is not None and entry.longitude is not None:
                location: dict[str, Any] = {
                    "latitude": entry.latitude,
                    "longitude": entry.longitude,
                }
                if entry.location_name:
                    location["place"] = entry.location_name
                item["location"] = location

            photos: list[dict[str, Any]] = []
            for media in entry.media:
                src = settings.MEDIA_DIR / media.storage_path
                if not src.is_file():
                    logger.warning(
                        "Media file missing on disk, skipped in Day One export: %s",
                        media.storage_path,
                    )
                    continue
                blob = src.read_bytes()
                ext, dayone_type = _dayone_photo_type(media)
                # Diarium matches archive members by the md5 prefix, so the
                # digest (not the LifeLogr filename) names the file.
                digest = hashlib.md5(blob, usedforsecurity=False).hexdigest()
                member = f"photos/{digest}.{ext}"
                photo: dict[str, Any] = {
                    "identifier": f"{digest}.{ext}",
                    "md5": digest,
                    "type": dayone_type,
                    "filename": f"{digest}.{ext}",
                    "size": len(blob),
                }
                if media.caption:
                    photo["caption"] = media.caption
                photos.append(photo)
                if member not in written_media:
                    zf.writestr(member, blob)
                    written_media.add(member)
                media_done += 1
                report("media", media_done, media_total)

            if photos:
                item["photos"] = photos
            items.append(item)
            report("render", index + 1, len(entries))

        document = {
            "metadata": {
                "version": "1.0",
                "generator": "LifeLogr",
                "skipped_encrypted": skipped_encrypted,
            },
            "entries": items,
        }
        zf.writestr(
            "Journal.json", json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")
        )
    return buf.getvalue()


# ── Daylio CSV export (Diarium's supported migration import) ────────────────
# Diarium has no generic JSON import; its documented migration path for CSV is
# Settings → Database → Migrate from other app, which reads the Daylio export
# format (columns confirmed both in the Diarium binary's importer strings and
# the vendor forum): full_date, date, weekday, time, mood, activities,
# note_title, note. Mood uses Daylio's five words — LifeLogr's "great" maps to
# Daylio's "rad" (both are the top of the 5-point scale Diarium rates 1–5).
_DAYLIO_HEADER = ["full_date", "date", "weekday", "time", "mood", "activities", "note_title", "note"]
_MOOD_TO_DAYLIO = {"awful": "awful", "bad": "bad", "meh": "meh", "good": "good", "great": "rad"}


def build_daylio_csv(entries: list[Entry]) -> bytes:
    """Serialize entries into Daylio CSV text (as bytes) for Diarium import.

    ``entries`` must have ``tag_associations`` loaded. Markdown is exported
    verbatim in ``note`` — Diarium renders CSV notes as plain text, so most
    markdown is legible as written; converting to HTML here would only bury
    the content in tags.
    """
    import csv as csv_mod
    import io

    buf = io.StringIO(newline="")
    writer = csv_mod.writer(buf)
    writer.writerow(_DAYLIO_HEADER)
    for entry in entries:
        ed = entry.entry_date
        if isinstance(ed, str):
            ed = date.fromisoformat(ed[:10])
        created = entry.created_at
        # Daylio's time is a plain local HH:MM; LifeLogr stores created_at in
        # UTC and the entry_date separately, so fall back to midnight rather
        # than inventing a timezone conversion the entry never recorded.
        hhmm = "00:00"
        if created is not None:
            hhmm = f"{created:%H:%M}"
        tags = [a.tag.name for a in entry.tag_associations if a.tag and a.tag.name]
        writer.writerow(
            [
                ed.isoformat(),
                f"{ed:%b} {ed.day}",
                f"{ed:%A}",
                hhmm,
                _MOOD_TO_DAYLIO.get((entry.mood or "").lower(), ""),
                " | ".join(tags),
                (entry.title or "").strip(),
                entry.body or "",
            ]
        )
    return buf.getvalue().encode("utf-8")


# ── Native archive export (entries + notes + media, full fidelity) ──────────
# A ZIP carrying the native JSON document plus every referenced media file.
# Bodies embed media as markdown/HTML URLs of the form
# `/api/v1/media/{id}/file`; each media record keeps its export-time id in
# `ref` so the importer can rewrite those URLs to the freshly created ids.
# v2 adds `notes.json` (notes, folders, pages + note attachments under
# `media/`) and per-entry `events`; v1 archives still import (keyed on the
# format field, notes.json simply absent).
ARCHIVE_FORMAT = "lifelogr-archive"
ARCHIVE_VERSION = 2


def build_archive(
    entries: list[Entry],
    notes: list[dict[str, Any]] | None = None,
    report: ProgressReporter = noop_reporter,
) -> bytes:
    """Serialize entries (+ optionally notes) and their media into the archive ZIP.

    ``entries`` must have ``tag_associations``, ``media`` and ``events``
    loaded. *notes* (optional) is the prebuilt note list from
    ``app.routers.entries._load_archive_notes`` — dicts with a ``media`` list
    whose ``path`` members are copied from MEDIA_DIR here. The JSON build and
    file copies are CPU/IO-bound — run via ``asyncio.to_thread``.
    *report* (optional) gets (phase, done, total) — "media" per file, then
    "finalize" for the JSON document.
    """
    import io
    import json as json_mod
    import zipfile

    from app.core.config import settings

    media_total = sum(
        1
        for e in entries
        for m in e.media
        if (settings.MEDIA_DIR / m.storage_path).is_file()
    )
    media_total += sum(
        1
        for n in notes or []
        for m in n.get("media", [])
        if (settings.MEDIA_DIR / m["path"][len("media/"):]).is_file()
    )
    media_done = 0
    if report is not None:
        report("media", 0, media_total)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        doc_entries = []
        for entry in entries:
            tags = [a.tag.name for a in entry.tag_associations if a.tag and a.tag.name]
            media_items = []
            for media in entry.media:
                # NOTE: encrypted entries' media travels **as ciphertext** here —
                # this is the native backup format (design §9): restore needs the
                # rows and files, and the blob on disk is already unreadable
                # without the key. Only the share exports (HTML/markdown/Diarium/
                # Day One) omit them.
                src = settings.MEDIA_DIR / media.storage_path
                if not src.is_file():
                    continue
                arcname = f"media/{media.storage_path}"
                zf.write(str(src), arcname)
                media_done += 1
                if report is not None:
                    report("media", media_done, media_total)
                media_items.append(
                    {
                        # Export-time id: bodies reference
                        # /api/v1/media/{ref}/file — the importer rewrites it.
                        "ref": media.id,
                        "path": arcname,
                        "filename": media.filename,
                        "media_type": media.media_type,
                        "caption": media.caption,
                        "is_inline": media.is_inline,
                    }
                )
            doc_entries.append(
                {
                    "entry_date": str(entry.entry_date),
                    "title": entry.title,
                    "body": entry.body,
                    "mood": entry.mood,
                    "tags": tags,
                    "latitude": entry.latitude,
                    "longitude": entry.longitude,
                    "media": media_items,
                    "events": [
                        {"kind": ev.kind, "content": ev.content, "label": ev.label}
                        for ev in getattr(entry, "events", ())
                    ],
                }
            )
        doc = {
            "format": ARCHIVE_FORMAT,
            "version": ARCHIVE_VERSION,
            "entries": doc_entries,
        }
        # Note attachment files live under the same media/ tree (their
        # storage_path is already notes/-prefixed, so it can't collide with
        # entry media's YYYY/MM paths).
        for note in notes or []:
            for m in note.get("media", []):
                src = settings.MEDIA_DIR / m["path"][len("media/"):]
                if src.is_file():
                    zf.write(str(src), m["path"])
                    media_done += 1
                    if report is not None:
                        report("media", media_done, media_total)
        if notes:
            doc["notes"] = notes
        if report is not None:
            report("finalize", 1, 1)
        zf.writestr("lifelogr.json", json_mod.dumps(doc, ensure_ascii=False, indent=2))
    return buf.getvalue()
