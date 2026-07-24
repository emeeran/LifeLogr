"""Business logic for notes."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy.sql.expression import Select as Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.note import Note, NoteFolder, NotePage, NoteTag
from app.schemas.note import (
    NoteCreate,
    NoteFolderCreate,
    NoteFolderUpdate,
    NotePageCreate,
    NotePageReorderItem,
    NotePageUpdate,
    NoteUpdate,
)

logger = logging.getLogger(__name__)


def _note_list_options() -> tuple[Any, ...]:
    """Eager-load tags + every scalar column EXCEPT ``body``.

    Built lazily (per-query) so it doesn't trigger mapper configuration at
    import. ``pages`` is intentionally NOT loaded — each page carries its own
    body and isn't needed for list rows (loaded on demand for the editor).
    """
    return (
        load_only(
            Note.id,
            Note.folder_id,
            Note.title,
            Note.is_pinned,
            Note.color,
            Note.is_encrypted,
            Note.encrypted_at,
            Note.created_at,
            Note.updated_at,
        ),
        selectinload(Note.tag_associations).selectinload(NoteTag.tag),
    )


class NoteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Notes ──────────────────────────────────────────────────────────────

    async def create(self, data: NoteCreate) -> Note:
        """Create a new note."""
        note = Note(
            title=data.title,
            body=data.body,
            folder_id=data.folder_id,
            is_pinned=data.is_pinned,
            color=data.color,
        )
        self.db.add(note)
        await self.db.flush()
        if data.tag_ids:
            self.db.add_all([NoteTag(note_id=note.id, tag_id=tid) for tid in data.tag_ids])
            await self.db.flush()
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def get(self, note_id: int) -> Note:
        """Return a single non-deleted note by ID."""
        result = await self.db.execute(
            select(Note).where(Note.id == note_id, Note.is_deleted == False)  # noqa: E712
        )
        note = result.scalar_one_or_none()
        if not note:
            raise NotFoundError(f"Note {note_id} not found")
        return note

    async def list_notes(
        self,
        offset: int,
        limit: int,
        folder_id: int | None = None,
        tag_ids: list[int] | None = None,
        is_pinned: bool | None = None,
    ) -> tuple[list[Note], int]:
        """Return paginated notes (pinned-first, then recently-updated) and total count."""
        base_q = select(Note).options(*_note_list_options()).where(Note.is_deleted.is_(False))
        base_q = self._apply_filters(base_q, folder_id, tag_ids, is_pinned)
        count_q = self._apply_filters(
            select(func.count()).select_from(Note).where(Note.is_deleted.is_(False)),
            folder_id,
            tag_ids,
            is_pinned,
        )
        total = (await self.db.execute(count_q)).scalar_one()
        result = await self.db.execute(
            base_q.order_by(Note.is_pinned.desc(), Note.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def body_snippets(self, note_ids: list[int]) -> dict[int, str]:
        """Server-side ~300-char body snippets (empty for encrypted notes)."""
        if not note_ids:
            return {}
        rows = await self.db.execute(
            select(Note.id, func.substr(Note.body, 1, 300)).where(
                Note.id.in_(note_ids), Note.is_encrypted == False  # noqa: E712
            )
        )
        return {row[0]: (row[1] or "") for row in rows.all()}

    async def update(self, note_id: int, data: NoteUpdate) -> Note:
        """Update note fields and/or tags of an existing note."""
        note = await self.get(note_id)
        if data.title is not None:
            note.title = data.title
        if data.body is not None:
            note.body = data.body
        if data.is_pinned is not None:
            note.is_pinned = data.is_pinned
        if data.color is not None:
            note.color = data.color
        if data.clear_folder:
            note.folder_id = None
        elif data.folder_id is not None:
            note.folder_id = data.folder_id
        if data.tag_ids is not None:
            current = {a.tag_id for a in note.tag_associations}
            desired = set(data.tag_ids)
            to_add = desired - current
            to_remove = current - desired
            if to_add:
                self.db.add_all([NoteTag(note_id=note_id, tag_id=tid) for tid in to_add])
            if to_remove:
                from sqlalchemy import delete

                await self.db.execute(
                    delete(NoteTag).where(NoteTag.note_id == note_id, NoteTag.tag_id.in_(to_remove))
                )
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def soft_delete(self, note_id: int) -> None:
        """Mark note as deleted. The FTS soft-delete trigger removes it from notes_fts."""
        note = await self.get(note_id)
        note.is_deleted = True
        note.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def restore(self, note_id: int) -> Note:
        """Un-delete a soft-deleted note (the fts_note_restore trigger re-indexes it)."""
        result = await self.db.execute(select(Note).where(Note.id == note_id))
        note = result.scalar_one_or_none()
        if note is None:
            raise NotFoundError(f"Note {note_id} not found")
        if not note.is_deleted:
            return note  # already live — idempotent
        note.is_deleted = False
        note.deleted_at = None
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def set_pinned(self, note_id: int, pinned: bool) -> Note:
        """Toggle pin state on a note."""
        note = await self.get(note_id)
        note.is_pinned = pinned
        await self.db.commit()
        await self.db.refresh(note)
        return note

    # ── Sub-pages (EPIM-style page tabs) ────────────────────────────────────

    async def create_page(self, note_id: int, data: NotePageCreate) -> NotePage:
        """Append a new page tab to a note (sort_order = current max + 1)."""
        await self.get(note_id)  # raises NotFoundError if the note doesn't exist
        max_order = (
            await self.db.execute(
                select(func.coalesce(func.max(NotePage.sort_order), -1)).where(
                    NotePage.note_id == note_id
                )
            )
        ).scalar_one()
        page = NotePage(note_id=note_id, title=data.title, body=data.body, sort_order=max_order + 1)
        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)
        return page

    async def update_page(self, note_id: int, page_id: int, data: NotePageUpdate) -> NotePage:
        page = await self._get_page(note_id, page_id)
        if data.title is not None:
            page.title = data.title
        if data.body is not None:
            page.body = data.body
        if data.sort_order is not None:
            page.sort_order = data.sort_order
        await self.db.commit()
        await self.db.refresh(page)
        return page

    async def delete_page(self, note_id: int, page_id: int) -> None:
        page = await self._get_page(note_id, page_id)
        await self.db.delete(page)
        await self.db.commit()

    async def reorder_pages(self, note_id: int, items: list[NotePageReorderItem]) -> None:
        """Set sort_order for the given pages (all scoped to note_id)."""
        await self.get(note_id)
        order_map = {it.id: it.sort_order for it in items}
        rows = (
            (
                await self.db.execute(
                    select(NotePage).where(
                        NotePage.note_id == note_id, NotePage.id.in_(list(order_map))
                    )
                )
            )
            .scalars()
            .all()
        )
        for page in rows:
            page.sort_order = order_map[page.id]
        await self.db.commit()

    async def _get_page(self, note_id: int, page_id: int) -> NotePage:
        result = await self.db.execute(
            select(NotePage).where(NotePage.note_id == note_id, NotePage.id == page_id)
        )
        page = result.scalar_one_or_none()
        if page is None:
            raise NotFoundError(f"Note page {page_id} not found")
        return page

    async def search(self, query: str, offset: int, limit: int) -> tuple[list[Note], int]:
        """Full-text search via the notes_fts index (falls back to ILIKE on error)."""
        from sqlalchemy import text as sa_text

        # Quote each token so special characters don't break the FTS5 MATCH parser.
        fts_query = " ".join(f'"{tok}"' for tok in query.split() if tok.strip())

        try:
            fts_sql = sa_text(
                """
                SELECT n.id FROM notes_fts fts
                JOIN notes n ON n.id = fts.rowid
                WHERE notes_fts MATCH :q AND n.is_deleted = 0
                ORDER BY bm25(notes_fts)
                LIMIT :lim OFFSET :off
                """
            )
            rows = (
                await self.db.execute(fts_sql, {"q": fts_query, "lim": limit, "off": offset})
            ).fetchall()
            note_ids = [r[0] for r in rows]
            if note_ids:
                count_sql = sa_text(
                    "SELECT COUNT(*) FROM notes_fts fts JOIN notes n ON n.id = fts.rowid "
                    "WHERE notes_fts MATCH :q AND n.is_deleted = 0"
                )
                total = (await self.db.execute(count_sql, {"q": fts_query})).scalar_one()
                result = await self.db.execute(
                    select(Note).options(*_note_list_options()).where(Note.id.in_(note_ids))
                )
                note_map = {n.id: n for n in result.scalars().all()}
                return [note_map[nid] for nid in note_ids if nid in note_map], total
            # FTS returned 0 rows — fall through to ILIKE (e.g. triggers missing in test DB).
        except Exception:
            logger.warning("Note FTS search failed, falling back to ILIKE", exc_info=True)

        pattern = f"%{query}%"
        base = select(Note).options(*_note_list_options()).where(
            Note.is_deleted == False,  # noqa: E712
            (Note.body.ilike(pattern)) | (Note.title.ilike(pattern)),
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        result = await self.db.execute(
            base.order_by(Note.updated_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    @staticmethod
    def _apply_filters(
        q: Select[Any],
        folder_id: int | None,
        tag_ids: list[int] | None,
        is_pinned: bool | None,
    ) -> Select[Any]:
        """Apply optional filters to a note query. Tag filtering uses a subquery
        (not a join) so a note matching multiple tags isn't double-counted."""
        if folder_id is not None:
            q = q.where(Note.folder_id == folder_id)
        if tag_ids:
            q = q.where(Note.id.in_(select(NoteTag.note_id).where(NoteTag.tag_id.in_(tag_ids))))
        if is_pinned is not None:
            q = q.where(Note.is_pinned == is_pinned)
        return q

    # ── Folders ────────────────────────────────────────────────────────────

    async def list_folders(self) -> list[tuple[NoteFolder, int]]:
        """Return non-deleted folders with their live note counts."""
        folders = list(
            (
                await self.db.execute(
                    select(NoteFolder)
                    .where(NoteFolder.is_deleted == False)  # noqa: E712
                    .order_by(NoteFolder.sort_order, NoteFolder.name)
                )
            )
            .scalars()
            .all()
        )
        if not folders:
            return []
        counts_rows = (
            await self.db.execute(
                select(Note.folder_id, func.count(Note.id))
                .where(Note.is_deleted == False, Note.folder_id.in_([f.id for f in folders]))  # noqa: E712
                .group_by(Note.folder_id)
            )
        ).all()
        counts = {fid: cnt for fid, cnt in counts_rows}
        return [(f, counts.get(f.id, 0)) for f in folders]

    async def create_folder(self, data: NoteFolderCreate) -> NoteFolder:
        folder = NoteFolder(
            name=data.name,
            parent_id=data.parent_id,
            color=data.color,
            sort_order=data.sort_order,
        )
        self.db.add(folder)
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    async def update_folder(self, folder_id: int, data: NoteFolderUpdate) -> NoteFolder:
        folder = await self._get_folder(folder_id)
        if data.name is not None:
            folder.name = data.name
        if data.color is not None:
            folder.color = data.color
        if data.sort_order is not None:
            folder.sort_order = data.sort_order
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    async def soft_delete_folder(self, folder_id: int) -> None:
        """Soft-delete a folder. Notes keep their folder_id (visible in 'All Notes');
        the DB-level SET NULL only fires on a hard delete."""
        folder = await self._get_folder(folder_id)
        folder.is_deleted = True
        folder.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def _get_folder(self, folder_id: int) -> NoteFolder:
        result = await self.db.execute(
            select(NoteFolder).where(
                NoteFolder.id == folder_id,
                NoteFolder.is_deleted == False,  # noqa: E712
            )
        )
        folder = result.scalar_one_or_none()
        if not folder:
            raise NotFoundError(f"Note folder {folder_id} not found")
        return folder
