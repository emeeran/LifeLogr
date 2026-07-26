"""Notes export/import: Markdown ZIP, JSON, HTML — mirrors the entries flow.

Encrypted notes are never exported as ciphertext: their body is replaced with a
placeholder and ``encrypted: true`` is flagged in frontmatter/JSON, so the note's
existence is preserved without leaking undecryptable content. Imported notes are
always created non-encrypted (the ciphertext can't be restored without the key).
"""

from __future__ import annotations

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

from app.models.note import Note, NoteFolder, NoteTag
from app.models.tag import Tag

_ENCRYPTED_PLACEHOLDER = "[encrypted — body not exported]"


class NotesExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._md = MarkdownIt()

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

    @staticmethod
    def _body(note: Note) -> str:
        return _ENCRYPTED_PLACEHOLDER if note.is_encrypted else (note.body or "")

    @staticmethod
    def _slug(title: str | None, idx: int) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", (title or f"note-{idx}").strip().lower()).strip("-")
        return (base or f"note-{idx}")[:80]

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
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, n in enumerate(notes, start=1):
                zf.writestr(
                    f"notes/{self._slug(n.title, i)}.md",
                    self._frontmatter(n) + self._body(n),
                )
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {"format": "lifelogr-notes", "version": 1, "exported_notes": len(notes)}, indent=2
                ),
            )
        buf.seek(0)
        return buf.getvalue()

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
    async def import_json(self, raw: bytes) -> dict[str, int]:
        data = json.loads(raw)
        items = data.get("notes") if isinstance(data, dict) else data
        return await self._import_items(items or [])

    async def import_markdown_zip(self, raw: bytes) -> dict[str, int]:
        items: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith("manifest.json") or not name.endswith(".md"):
                    continue
                items.append(self._parse_md(zf.read(name).decode("utf-8", "ignore")))
        return await self._import_items(items)

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

    async def _import_items(self, items: list[dict[str, Any]]) -> dict[str, int]:
        from app.schemas.note import NoteCreate, NotePageCreate
        from app.services.note_service import NoteService

        svc = NoteService(self.db)
        imported = 0
        skipped = 0
        for it in items:
            try:
                folder_id = await self._resolve_folder(it.get("folder"))
                tag_ids = await self._resolve_tags(it.get("tags") or [])
                note = await svc.create(
                    NoteCreate(
                        title=it.get("title"),
                        body=it.get("body") or "",
                        folder_id=folder_id,
                        tag_ids=tag_ids,
                        is_pinned=bool(it.get("is_pinned")),
                        color=it.get("color"),
                    )
                )
                for p in it.get("pages") or []:
                    await svc.create_page(
                        note.id, NotePageCreate(title=p.get("title"), body=p.get("body") or "")
                    )
                imported += 1
            except Exception:
                skipped += 1
        return {"imported": imported, "skipped": skipped}

    async def _resolve_folder(self, name: str | None) -> int | None:
        if not name:
            return None
        res = await self.db.execute(
            select(NoteFolder).where(
                NoteFolder.name == name, NoteFolder.is_deleted == False  # noqa: E712
            )
        )
        folder = res.scalar_one_or_none()
        if folder:
            return folder.id
        from app.schemas.note import NoteFolderCreate
        from app.services.note_service import NoteService

        return (await NoteService(self.db).create_folder(NoteFolderCreate(name=name))).id

    async def _resolve_tags(self, names: list[str]) -> list[int]:
        ids: list[int] = []
        for name in names:
            res = await self.db.execute(select(Tag).where(Tag.name == name))
            tag = res.scalar_one_or_none()
            if tag is None:
                tag = Tag(name=name)
                self.db.add(tag)
                await self.db.flush()
            ids.append(tag.id)
        return ids
