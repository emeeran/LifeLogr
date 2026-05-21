"""Revision service — auto-snapshot, diff, and restore for journal entries."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.entry import Entry
from app.models.revision import EntryRevision
from app.schemas.revision import RevisionDiffResponse


class RevisionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_snapshot(self, entry: Entry, reason: str = "edit") -> EntryRevision:
        """Create a revision snapshot from the current state of an entry."""
        # Determine next revision number
        result = await self.db.execute(
            select(func.coalesce(func.max(EntryRevision.revision_number), 0)).where(
                EntryRevision.entry_id == entry.id
            )
        )
        max_rev = result.scalar_one()
        revision = EntryRevision(
            entry_id=entry.id,
            revision_number=max_rev + 1,
            title=entry.title,
            body=entry.body,
            mood=entry.mood,
            snapshot_reason=reason,
        )
        self.db.add(revision)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(revision)
        return revision

    async def list_revisions(
        self, entry_id: int, offset: int = 0, limit: int = 50
    ) -> tuple[list[EntryRevision], int]:
        """Return paginated revision history for an entry."""
        await self._get_entry(entry_id)

        count_q = select(func.count()).select_from(EntryRevision).where(
            EntryRevision.entry_id == entry_id
        )
        total = (await self.db.execute(count_q)).scalar_one()

        q = (
            select(EntryRevision)
            .where(EntryRevision.entry_id == entry_id)
            .order_by(EntryRevision.revision_number.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(q)
        return list(result.scalars().all()), total

    async def get_revision(self, entry_id: int, revision_number: int) -> EntryRevision:
        """Return a specific revision."""
        await self._get_entry(entry_id)
        result = await self.db.execute(
            select(EntryRevision).where(
                EntryRevision.entry_id == entry_id,
                EntryRevision.revision_number == revision_number,
            )
        )
        rev = result.scalar_one_or_none()
        if not rev:
            raise NotFoundError(f"Revision {revision_number} not found for entry {entry_id}")
        return rev

    async def diff(
        self, entry_id: int, from_rev: int, to_rev: int
    ) -> RevisionDiffResponse:
        """Compare two revisions of an entry."""
        from_revision = await self.get_revision(entry_id, from_rev)
        to_revision = await self.get_revision(entry_id, to_rev)

        return RevisionDiffResponse(
            from_revision=from_rev,
            to_revision=to_rev,
            title_changed=from_revision.title != to_revision.title,
            body_changed=from_revision.body != to_revision.body,
            mood_changed=from_revision.mood != to_revision.mood,
            from_title=from_revision.title,
            to_title=to_revision.title,
            from_body=from_revision.body,
            to_body=to_revision.body,
            from_mood=from_revision.mood,
            to_mood=to_revision.mood,
        )

    async def restore(self, entry_id: int, revision_number: int) -> Entry:
        """Restore an entry to a previous revision state.

        Creates a snapshot of the current state before restoring.
        """
        entry = await self._get_entry(entry_id)
        rev = await self.get_revision(entry_id, revision_number)

        # Snapshot current state before restoring
        await self.create_snapshot(entry, reason="pre-restore")

        entry.title = rev.title
        entry.body = rev.body
        entry.mood = rev.mood
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def _get_entry(self, entry_id: int) -> Entry:
        result = await self.db.execute(
            select(Entry).where(Entry.id == entry_id, Entry.is_deleted == False)  # noqa: E712
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found")
        return entry
