"""Migration: encrypt existing attachments of encrypted items (SEC-MEDIA-5).

Implements ``docs/design/media-encryption.md`` §7. Policy (§5) is that media
of an encrypted entry/note should be encrypted at rest — new uploads are
handled at write time (``ENCRYPT_MEDIA``); this module moves **existing**
plaintext files over, and purges plaintext thumbnails that predate the
encrypted thumb cache.

Rules:
* Dry run first — counts and bytes, writes nothing.
* Resumable: a file already starting with the ``LLM1`` magic is skipped, so
  reruns are safe and a crash mid-run loses nothing.
* Atomic per file: tmp write → fsync → ``replace``; the original is never
  removed before the ciphertext is fully on disk. On any failure the original
  stays and the path is reported, never silently dropped.
* Plaintext items are never touched.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.models.note import Note
from app.models.note_media import NoteMedia
from app.models.video_note import VideoNote
from app.services import media_crypto
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)


async def encrypt_pending_attachments(db: AsyncSession, *, dry_run: bool) -> dict[str, Any]:
    """Encrypt plaintext media of encrypted entries/notes; purge stale thumbs.

    Returns a report dict (``candidates``, ``plaintext_bytes``, ``stale_thumbs``,
    ``updated``, ``thumbs_purged``, ``errors``).
    """
    rows = list((await db.execute(_entry_media_query())).scalars().all())
    rows += (await db.execute(_note_media_query())).scalars().all()
    rows += (await db.execute(_video_note_query())).scalars().all()

    candidates: list[tuple[Media | NoteMedia | VideoNote, Path]] = []
    stale_thumbs = 0
    plaintext_bytes = 0
    for media in rows:
        full_path = settings.MEDIA_DIR / media.storage_path
        if not full_path.is_file():
            continue  # missing on disk; the integrity check reports it elsewhere
        encrypted, _plain_len = await asyncio.to_thread(media_crypto.probe_file, full_path)
        # VideoNotes have no thumbnail cache (only Media/NoteMedia do).
        thumb = (
            MediaService._thumb_path_for(media) if isinstance(media, (Media, NoteMedia)) else None
        )
        if encrypted:
            # Blob already done — the only remaining work is a thumb written
            # before the encrypted cache existed.
            if thumb is not None and thumb.is_file():
                stale_thumbs += 1
                if not dry_run:
                    await asyncio.to_thread(thumb.unlink)
            continue
        candidates.append((media, full_path))
        plaintext_bytes += (await asyncio.to_thread(full_path.stat)).st_size


    if dry_run:
        return {
            "dry_run": True,
            "candidates": len(candidates),
            "plaintext_bytes": plaintext_bytes,
            "stale_thumbs": stale_thumbs,
            "updated": 0,
            "thumbs_purged": 0,
            "errors": [],
        }

    updated = 0
    thumbs_purged = 0
    errors: list[str] = []
    for media, full_path in candidates:
        try:
            await asyncio.to_thread(_encrypt_in_place, full_path, media.storage_path)
            updated += 1
            thumb = (
                MediaService._thumb_path_for(media) if isinstance(media, (Media, NoteMedia)) else None
            )
            if thumb is not None and thumb.is_file():
                await asyncio.to_thread(thumb.unlink)
                thumbs_purged += 1
        except Exception:
            # Never delete the only copy: the original stays, the failure is
            # reported and a rerun picks the file up again.
            logger.warning(
                "Media encryption migration failed for %s", media.storage_path, exc_info=True
            )
            errors.append(media.storage_path)
    if updated or stale_thumbs:
        logger.info(
            "Media encryption migration: encrypted %d file(s), purged %d stale thumb(s), %d error(s)",
            updated,
            thumbs_purged + stale_thumbs,
            len(errors),
        )
    return {
        "dry_run": False,
        "candidates": len(candidates),
        "plaintext_bytes": plaintext_bytes,
        "stale_thumbs": stale_thumbs,
        "updated": updated,
        "thumbs_purged": thumbs_purged + stale_thumbs,
        "errors": errors,
    }


def _entry_media_query() -> Select[Any]:
    return (
        select(Media)
        .join(Entry, Media.entry_id == Entry.id)
        .where(Entry.is_encrypted == True, ~Entry.is_deleted)  # noqa: E712
        .order_by(Media.id)
    )


def _note_media_query() -> Select[Any]:
    return (
        select(NoteMedia)
        .join(Note, NoteMedia.note_id == Note.id)
        .where(Note.is_encrypted == True, ~Note.is_deleted)  # noqa: E712
        .order_by(NoteMedia.id)
    )


def _video_note_query() -> Select[Any]:
    """Clips of encrypted entries — the third attachment store."""
    return (
        select(VideoNote)
        .join(Entry, VideoNote.entry_id == Entry.id)
        .where(Entry.is_encrypted == True, ~Entry.is_deleted)  # noqa: E712
        .order_by(VideoNote.id)
    )


def _encrypt_in_place(full_path: Path, storage_path: str) -> None:
    """Read → chunk-encrypt → tmp → fsync → atomic replace."""
    plaintext = full_path.read_bytes()
    if media_crypto.is_encrypted(plaintext):
        return
    blob = media_crypto.encrypt_media(plaintext, storage_path)
    tmp = full_path.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(full_path)
    finally:
        tmp.unlink(missing_ok=True)
