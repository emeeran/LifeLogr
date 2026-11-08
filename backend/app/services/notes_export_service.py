"""Notes export/import: Markdown ZIP, JSON, HTML — mirrors the entries flow.

Encrypted notes are never exported as ciphertext: their body is replaced with a
placeholder and ``encrypted: true`` is flagged in frontmatter/JSON, so the note's
existence is preserved without leaking undecryptable content. Imported notes are
always created non-encrypted (the ciphertext can't be restored without the key).
"""

from __future__ import annotations

import asyncio
import html as _html
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from markdown_it import MarkdownIt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import MediaSizeError
from app.core.jobs import ProgressReporter, noop_reporter
from app.models.note import Note, NoteFolder, NoteTag

ENCRYPTED_PLACEHOLDER = "[encrypted — body not exported]"


class NotesExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # ``html: False`` so a ``<script>`` pasted into a note body is escaped
        # (not rendered) in the exported HTML — raw HTML here is stored XSS.
        self._md = MarkdownIt("default", {"html": False})

    # ── Load ──
    async def _get_notes(self) -> list[Note]:
        res = await self.db.execute(
            select(Note)
            .where(Note.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Note.folder),
                selectinload(Note.tag_associations).selectinload(NoteTag.tag),
                selectinload(Note.pages),
            )
            .order_by(Note.created_at)
        )
        return list(res.scalars())

    async def _get_note(self, note_id: int) -> Note | None:
        res = await self.db.execute(
            select(Note)
            .where(Note.id == note_id, Note.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Note.folder),
                selectinload(Note.tag_associations).selectinload(NoteTag.tag),
                selectinload(Note.pages),
            )
        )
        return res.scalar_one_or_none()

    @staticmethod
    def _body(note: Note) -> str:
        return ENCRYPTED_PLACEHOLDER if note.is_encrypted else (note.body or "")

    @staticmethod
    def _slug(title: str | None, idx: int) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", (title or f"note-{idx}").strip().lower()).strip("-")
        return (base or f"note-{idx}")[:80]

    @classmethod
    def _zip_name(cls, title: str | None, idx: int, used: set[str]) -> str:
        """Collision-free ``notes/<slug>.md`` archive member name.

        Two notes with the same title (or both untitled) previously produced the
        same member name and the later ``writestr`` silently replaced the earlier
        one — the export lost notes. Falls back to ``<slug>-<n>``, counting up
        from the note's export index, until the name is free.
        """
        name = f"notes/{cls._slug(title, idx)}.md"
        counter = idx
        while name in used:
            name = f"notes/{cls._slug(title, idx)}-{counter}.md"
            counter += 1
        used.add(name)
        return name

    # ── Export ──
    async def export_json(self) -> bytes:
        notes = await self._get_notes()
        payload = {
            "app": "lifelogr",
            "kind": "notes",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "notes": [
                {
                    "title": n.title,
                    "body": self._body(n),
                    "is_encrypted": n.is_encrypted,
                    "is_pinned": n.is_pinned,
                    "color": n.color,
                    "folder": n.folder.name if n.folder else None,
                    "tags": [nt.tag.name for nt in n.tag_associations],
                    "pages": [{"title": p.title, "body": p.body} for p in n.pages],
                }
                for n in notes
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    async def export_markdown(self) -> bytes:
        notes = await self._get_notes()
        # Zip assembly is blocking I/O + deflate compression — offload the loop.
        return await asyncio.to_thread(self._build_markdown_zip, notes)

    def _build_markdown_zip(self, notes: list[Note]) -> bytes:
        buf = io.BytesIO()
        used: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, n in enumerate(notes, start=1):
                zf.writestr(
                    self._zip_name(n.title, i, used),
                    self._frontmatter(n) + self._body(n),
                )
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {"format": "lifelogr-notes", "version": 1, "exported_notes": len(notes)},
                    indent=2,
                ),
            )
        buf.seek(0)
        return buf.getvalue()

    async def export_single_markdown(self, note_id: int) -> tuple[str, bytes] | None:
        """One note as ``(filename, markdown bytes)`` — frontmatter + body.

        Returns ``None`` if the note doesn't exist (caller → 404). Encrypted
        notes export the placeholder body, mirroring the bulk path.
        """
        n = await self._get_note(note_id)
        if n is None:
            return None
        filename = f"{self._slug(n.title, note_id)}.md"
        content = (self._frontmatter(n) + self._body(n)).encode("utf-8")
        return filename, content

    def _frontmatter(self, n: Note) -> str:
        lines = ["---"]
        if n.title:
            lines.append(f"title: {n.title}")
        if n.folder:
            lines.append(f"folder: {n.folder.name}")
        tags = [nt.tag.name for nt in n.tag_associations]
        if tags:
            lines.append("tags: [" + ", ".join(tags) + "]")
        lines.append(f"pinned: {'true' if n.is_pinned else 'false'}")
        if n.color:
            lines.append(f"color: {n.color}")
        if n.is_encrypted:
            lines.append("encrypted: true")
        lines += ["---", ""]
        return "\n".join(lines)

    async def export_html(self) -> str:
        notes = await self._get_notes()
        parts = [
            "<!doctype html><html><head><meta charset='utf-8'>",
            "<title>LifeLogr Notes</title>",
            "<style>body{font-family:system-ui,sans-serif;max-width:780px;margin:2rem auto;"
            "padding:0 1rem;line-height:1.6;color:#111}article{border-bottom:1px solid #ddd;"
            "padding:1.2rem 0}h1{font-size:1.4rem;margin:0 0 .5rem}</style></head><body>",
        ]
        for n in notes:
            body_html = self._md.render(self._body(n))
            parts.append(
                f"<article><h1>{_html.escape(n.title or 'Untitled')}</h1>{body_html}</article>"
            )
        parts.append("</body></html>")
        return "".join(parts)

    # ── Import ──
    def parse_json(self, raw: bytes) -> list[dict[str, Any]]:
        data = json.loads(raw)
        items = data.get("notes") if isinstance(data, dict) else data
        return items or []

    def parse_markdown_zip(self, raw: bytes) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith("manifest.json") or not name.endswith(".md"):
                    continue
                items.append(self._parse_md(zf.read(name).decode("utf-8", "ignore")))
        return items

    async def import_json(self, raw: bytes, report: ProgressReporter = noop_reporter) -> dict[str, Any]:
        return await self._import_items(self.parse_json(raw), report=report)

    async def import_markdown_zip(
        self, raw: bytes, report: ProgressReporter = noop_reporter
    ) -> dict[str, Any]:
        return await self._import_items(self.parse_markdown_zip(raw), report=report)

    async def import_single_markdown(self, raw: bytes) -> dict[str, Any]:
        """Import one Markdown file as one new note; returns its id on success."""
        item = self._parse_md(raw.decode("utf-8", "ignore"))
        res = await self._import_items([item])
        ids = res.get("note_ids") or []
        return {
            "imported": res["imported"],
            "skipped": res["skipped"],
            "note_id": ids[0] if ids else None,
        }

    @staticmethod
    def _parse_md(raw: str) -> dict[str, Any]:
        lines = raw.splitlines()
        meta: dict[str, str] = {}
        body_start = 0
        if lines and lines[0].strip() == "---":
            i = 1
            while i < len(lines) and lines[i].strip() != "---":
                if ":" in lines[i]:
                    k, _, v = lines[i].partition(":")
                    meta[k.strip()] = v.strip()
                i += 1
            body_start = i + 1
        body = "\n".join(lines[body_start:]).strip("\n")
        tags_raw = re.sub(r"[\[\]]", "", meta.get("tags", ""))
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return {
            "title": meta.get("title") or None,
            "body": body,
            "folder": meta.get("folder") or None,
            "tags": tags,
            "is_pinned": meta.get("pinned", "false").lower() == "true",
            "color": meta.get("color") or None,
        }

    async def _import_items(
        self, items: list[dict[str, Any]], report: ProgressReporter = noop_reporter
    ) -> dict[str, Any]:
        from app.schemas.note import NoteCreate, NotePageCreate
        from app.services.note_service import NoteService

        svc = NoteService(self.db)
        imported = 0
        skipped = 0
        note_ids: list[int] = []
        total = len(items)
        if report is not None:
            report("insert", 0, total)
        for idx, it in enumerate(items):
            try:
                folder_id = await self._resolve_folder(it.get("folder"))
                # Tags live in the text: write the item's tags as #tokens into the
                # body so the body-driven sync links them on create.
                raw_body = it.get("body") or ""
                tag_names = [t for t in (it.get("tags") or []) if t]
                if tag_names:
                    raw_body = raw_body.rstrip() + "\n\n" + " ".join(f"#{t}" for t in tag_names)
                note = await svc.create(
                    NoteCreate(
                        title=it.get("title"),
                        body=raw_body,
                        folder_id=folder_id,
                        is_pinned=bool(it.get("is_pinned")),
                        color=it.get("color"),
                    )
                )
                for p in it.get("pages") or []:
                    await svc.create_page(
                        note.id, NotePageCreate(title=p.get("title"), body=p.get("body") or "")
                    )
                # Attachments (native archive v2 only — other import paths
                # never carry media). Bodies reference
                # /api/v1/notes/{old_note}/media/{old_media}/file; rewrite to
                # the fresh ids after the rows exist.
                media_items = it.get("media") or []
                if media_items:
                    ref_map = await self._attach_media(note.id, media_items)
                    if ref_map and note.body:
                        new_body = note.body
                        for old_media, (new_note, new_media) in ref_map.items():
                            # Old note id is unknown (the archive keeps only the
                            # media ref) — match any note id in the URL.
                            new_body = re.sub(
                                rf"/api(/v1)?/notes/\d+/media/{old_media}/file",
                                f"/api/v1/notes/{new_note}/media/{new_media}/file",
                                new_body,
                            )
                        if new_body != note.body:
                            note.body = new_body
                            await self.db.commit()
                            await self.db.refresh(note)
                imported += 1
                note_ids.append(note.id)
            except Exception:
                skipped += 1
            if report is not None:
                report("insert", idx + 1, total)
        return {"imported": imported, "skipped": skipped, "note_ids": note_ids}

    async def _attach_media(
        self, note_id: int, media_items: list[dict[str, Any]]
    ) -> dict[int, tuple[int, int]]:
        """Persist archive note-media payloads; return {old_media_id: (note_id, new_id)}.

        Bytes go through the same size cap and signature check as entry-media
        imports — an import path must never smuggle blocked file types.
        """
        import uuid
        from pathlib import Path as _Path

        from app.core.config import settings
        from app.models.note_media import NoteMedia

        ref_map: dict[int, tuple[int, int]] = {}
        for item in media_items:
            data = item.get("data") or b""
            if not data:
                continue
            filename = (item.get("filename") or "attachment.bin").strip() or "attachment.bin"
            if len(data) > settings.MAX_MEDIA_SIZE_BYTES:
                continue
            try:
                from app.services.media_service import check_signature

                check_signature(data[:64], filename)
            except MediaSizeError:
                continue
            media_type = (item.get("media_type") or "document").lower()
            if media_type not in ("image", "audio", "video", "document"):
                media_type = "document"
            stored_name = f"{uuid.uuid4()}{_Path(filename).suffix.lower()}"
            dest = settings.MEDIA_DIR / "notes" / stored_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            row = NoteMedia(
                note_id=note_id,
                filename=filename,
                media_type=media_type,
                file_size=len(data),
                storage_path=f"notes/{stored_name}",
                caption=item.get("caption") or None,
            )
            self.db.add(row)
            await self.db.flush()
            try:
                ref_map[int(item["ref"])] = (note_id, row.id)
            except (KeyError, TypeError, ValueError):
                pass
        return ref_map

    async def _resolve_folder(self, name: str | None) -> int | None:
        if not name:
            return None
        res = await self.db.execute(
            select(NoteFolder).where(
                NoteFolder.name == name,
                NoteFolder.is_deleted == False,  # noqa: E712
            )
        )
        folder = res.scalar_one_or_none()
        if folder:
            return folder.id
        from app.schemas.note import NoteFolderCreate
        from app.services.note_service import NoteService

        return (await NoteService(self.db).create_folder(NoteFolderCreate(name=name))).id
