"""Business logic for media attachments."""

import asyncio
import io
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError, NotFoundError, ValidationError
from app.models.entry import Entry
from app.models.media import Media

logger = logging.getLogger(__name__)

# Magic-number signatures for dangerous file types (reject these)
_BLOCKED_SIGNATURES: dict[bytes, str] = {
    b"MZ": "Windows executable",
    b"\x7fELF": "Linux executable",
    b"<script": "HTML script tag",
    b"<?php": "PHP script",
    b"<!DOCTYPE": "HTML document",
}

# Allowed MIME type prefixes
_ALLOWED_MIME_PREFIXES = {"image/", "video/", "audio/", "application/pdf", "text/"}

# Image types that can be converted to WebP
_CONVERTIBLE_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

# Max dimension for image resizing
_MAX_IMAGE_DIMENSION = 2048

# Chunk size for spooling an upload to disk (see ``spool_upload``).
_SPOOL_CHUNK_BYTES = 1024 * 1024

# Longest magic-number signature we test for, in bytes.
_MAX_SIGNATURE_LEN = max(len(sig) for sig in _BLOCKED_SIGNATURES)

# Standard user folders accepted by the path-import endpoint.
_STANDARD_USER_DIRS = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")
# Extra operator-configured import roots (comma-separated), mirroring
# ``BACKUP_ALLOWED_ROOTS``. Read from settings when the field exists, else from
# the environment — core/config.py is owned elsewhere.
_EXTRA_ROOTS_SETTING = "MEDIA_IMPORT_ALLOWED_ROOTS"


def _is_under(path: Path, root: Path) -> bool:
    """True if ``path`` is ``root`` itself or somewhere beneath it."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_hidden_component(path: Path, root: Path) -> bool:
    """True if any component of ``path`` below ``root`` starts with a dot."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part.startswith(".") for part in rel.parts)


def allowed_import_roots() -> list[Path]:
    """Roots the unauthenticated ``/from-path`` import endpoint may read from.

    Positive allowlist, mirroring ``app.core.paths.allowed_backup_roots``:

    * the standard user folders (Desktop, Documents, Downloads, Music, Pictures,
      Videos) — where dropped attachments realistically live;
    * the system temp dir — drag-drop staging and screenshot scratch space;
    * the home directory itself, **minus hidden (dot) directories** — the
      desktop drag-drop handler forwards paths from any visible folder (project
      dirs, mounts under home), so confining imports to the six standard folders
      would break real drops. Hidden folders are where the sensitive material
      lives (config, keys, app state), so they are denied wholesale;
    * extra operator-configured roots via ``MEDIA_IMPORT_ALLOWED_ROOTS``
      (comma-separated) — e.g. an external drive: ``/media,/mnt``.

    The explicit denylist (app data dir, ``~/.ssh``, ``~/.gnupg``, ``~/.config``)
    is applied afterwards in :func:`validate_import_path` and always wins.
    """
    extra = str(getattr(settings, _EXTRA_ROOTS_SETTING, "") or "") or os.environ.get(
        _EXTRA_ROOTS_SETTING, ""
    )

    home = Path.home().resolve()
    roots: list[Path] = [home / name for name in _STANDARD_USER_DIRS]
    tmp = Path(tempfile.gettempdir()).resolve()
    if tmp not in roots:
        roots.append(tmp)
    roots.append(home)
    for raw in extra.split(","):
        raw = raw.strip()
        if not raw:
            continue
        root = Path(raw).expanduser().resolve()
        if root not in roots:
            roots.append(root)
    return roots


def validate_import_path(path: str) -> Path:
    """Resolve and sandbox-check a user-supplied import path.

    Returns the resolved Path. Raises ``NotFoundError`` if the file is missing
    and ``ValidationError`` if it sits outside the allowlist or inside a denied
    location, so the unauthenticated endpoint can't be used to read arbitrary
    files.
    """
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        raise NotFoundError(f"File not found: {path}") from None

    home = Path.home().resolve()
    if not any(_is_under(p, root) for root in allowed_import_roots()):
        raise ValidationError(
            "Imports are restricted to files under your home directory"
        ) from None
    if _has_hidden_component(p, home):
        raise ValidationError("Imports from hidden folders are not allowed") from None
    for sensitive in (
        Path(settings.DATA_DIR).resolve(),
        home / ".ssh",
        home / ".gnupg",
        home / ".config",
    ):
        if _is_under(p, sensitive):
            raise ValidationError("Imports from this location are not allowed") from None
    return p


def read_head(path: Path, n: int = _MAX_SIGNATURE_LEN) -> bytes:
    """First ``n`` bytes of a file (magic-number checks; handle-safe)."""
    with path.open("rb") as f:
        return f.read(n)


async def spool_upload(file: UploadFile, max_bytes: int) -> tuple[Path, int]:
    """Stream an ``UploadFile`` to a temp file, enforcing ``max_bytes`` incrementally.

    ``await file.read()`` materialises the whole body in RAM *before* the 25 MB
    service check runs, so an oversized upload costs memory as well as bandwidth.
    Spooling in 1 MiB chunks (the pattern used by the backup import endpoint)
    aborts with :class:`MediaSizeError` the moment the cap is crossed.

    Returns ``(spool_path, size)``. The caller owns the spool file and must
    unlink it (``spool_path.unlink(missing_ok=True)``).
    """
    upload = tempfile.NamedTemporaryFile(delete=False)
    path = Path(upload.name)
    written = 0
    try:
        while True:
            chunk = await file.read(_SPOOL_CHUNK_BYTES)
            if not chunk:
                break
            if written + len(chunk) > max_bytes:
                raise MediaSizeError(f"File exceeds {max_bytes} bytes")
            upload.write(chunk)
            written += len(chunk)
        upload.flush()
        upload.close()
    except BaseException:
        upload.close()
        path.unlink(missing_ok=True)
        raise
    return path, written


# Extension → MIME mapping for path-based imports (Tauri native drag-drop gives
# a path, not a browser MIME type). Mirrors note_media_service; unknown
# extensions fall through to octet-stream, which upload() rejects.
_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "txt": "text/plain",
    "csv": "text/csv",
    "md": "text/markdown",
}


class MediaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _validate_upload_meta(filename: str, content_type: str, size: int) -> str:
        """Shared upload gate: size cap, MIME allowlist and filename sanitising.

        Returns the sanitised filename. Magic-number signatures are checked
        separately (:meth:`_check_signature`) so the streaming path can test just
        the head bytes instead of the whole payload.
        """
        if size > settings.MAX_MEDIA_SIZE_BYTES:
            raise MediaSizeError(f"File exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")

        if not any(content_type.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
            raise MediaSizeError(f"File type '{content_type}' not allowed")

        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename:
            raise MediaSizeError("Invalid filename")
        return safe_name

    @staticmethod
    def _check_signature(head: bytes, filename: str) -> None:
        """Reject a head sample of the payload matching a blocked signature."""
        for sig, label in _BLOCKED_SIGNATURES.items():
            if head[: len(sig)] == sig:
                logger.warning("Blocked upload of %s (detected %s)", filename, label)
                raise MediaSizeError(f"File type not allowed: detected {label}")

    async def _require_entry(self, entry_id: int) -> None:
        result = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        if not result.scalar_one_or_none():
            raise NotFoundError(f"Entry {entry_id} not found")

    async def _persist_media(
        self,
        entry_id: int,
        safe_name: str,
        content_type: str,
        media_type: str,
        stored_name: str,
        file_size: int,
        caption: str | None,
    ) -> Media:
        media = Media(
            entry_id=entry_id,
            filename=safe_name,
            media_type=media_type,
            file_size=file_size,
            storage_path=f"{media_type}s/{stored_name}",
            caption=caption,
        )
        self.db.add(media)
        await self.db.commit()
        await self.db.refresh(media)
        return media

    async def upload(
        self,
        entry_id: int,
        filename: str,
        content_type: str,
        file_data: bytes,
        caption: str | None = None,
    ) -> Media:
        """Store file on disk and create media record; reject > 25 MB."""
        safe_name = self._validate_upload_meta(filename, content_type, len(file_data))
        self._check_signature(file_data, filename)
        await self._require_entry(entry_id)

        media_type = self._classify_media(content_type)
        final_data = file_data
        final_ext = Path(safe_name).suffix or ".bin"
        if content_type in _CONVERTIBLE_IMAGE_TYPES:
            # PIL decode/resize/WebP-encode is CPU-bound — off the event loop so
            # a large screenshot can't stall every other request.
            final_data, converted = await asyncio.to_thread(
                MediaService._compress_to_webp, file_data
            )
            if converted:
                final_ext = ".webp"

        stored_name = f"{uuid.uuid4()}{final_ext}"
        full_path = settings.MEDIA_DIR / f"{media_type}s" / stored_name
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(full_path.write_bytes, final_data)

        return await self._persist_media(
            entry_id,
            safe_name,
            content_type,
            media_type,
            stored_name,
            len(final_data),
            caption,
        )

    async def upload_file(
        self,
        entry_id: int,
        filename: str,
        content_type: str,
        src: Path,
        caption: str | None = None,
        size: int | None = None,
    ) -> Media:
        """Store an already-spooled upload and create the media record.

        The streaming routers hand the temp file here instead of its bytes, so an
        oversized payload is rejected without ever being held in memory. The
        spool file is consumed (moved) on success — the caller still unlinks it,
        which is a safe no-op afterwards.
        """
        if size is None:
            size = (await asyncio.to_thread(src.stat)).st_size
        safe_name = self._validate_upload_meta(filename, content_type, size)

        head = await asyncio.to_thread(read_head, src)
        self._check_signature(head, filename)
        await self._require_entry(entry_id)

        media_type = self._classify_media(content_type)
        final_ext = Path(safe_name).suffix or ".bin"
        convert = content_type in _CONVERTIBLE_IMAGE_TYPES
        final_data = b""
        file_size = size
        if convert:
            # Images must be re-encoded anyway, so read + compress off-loop.
            data = await asyncio.to_thread(src.read_bytes)
            final_data, converted = await asyncio.to_thread(MediaService._compress_to_webp, data)
            if converted:
                final_ext = ".webp"
            file_size = len(final_data)

        stored_name = f"{uuid.uuid4()}{final_ext}"
        full_path = settings.MEDIA_DIR / f"{media_type}s" / stored_name
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        if convert:
            await asyncio.to_thread(full_path.write_bytes, final_data)
        else:
            # Everything else is moved straight into place — no re-read.
            await asyncio.to_thread(shutil.move, str(src), str(full_path))

        return await self._persist_media(
            entry_id, safe_name, content_type, media_type, stored_name, file_size, caption
        )

    async def upload_from_path(self, entry_id: int, path: str, caption: str | None = None) -> Media:
        """Read a local file by absolute path and import it as entry media.

        Used by the Tauri native drag-drop handler (WebKitGTK doesn't deliver
        HTML5 file drops, so the frontend receives a path, not a File object).

        Sandboxed by :func:`validate_import_path` (shared with the notes
        variant): a positive allowlist of user space plus the system temp dir,
        with sensitive locations denied, so the unauthenticated endpoint can't be
        used to read arbitrary files.
        """
        p = validate_import_path(path)
        ext = p.suffix.lower().lstrip(".")
        content_type = _EXT_TO_MIME.get(ext, "application/octet-stream")
        data = await asyncio.to_thread(p.read_bytes)
        return await self.upload(entry_id, p.name, content_type, data, caption)

    @staticmethod
    def _compress_to_webp(file_data: bytes) -> tuple[bytes, bool]:
        """Compress image and convert to WebP. Returns (data, was_converted)."""
        try:
            from PIL import Image
        except ImportError:
            logger.warning(
                "Image compression requires the 'image' extra. "
                'Install it with: uv pip install -e ".[image]". Storing original.'
            )
            return file_data, False

        try:
            img: Any = Image.open(io.BytesIO(file_data))

            # Strip EXIF orientation and convert to RGB if needed
            if hasattr(img, "transpose"):
                from PIL import ImageOps

                img = ImageOps.exif_transpose(img)

            # Resize if larger than max dimension
            if max(img.size) > _MAX_IMAGE_DIMENSION:
                resampling = getattr(Image, "Resampling", Image)
                img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION), resampling.LANCZOS)

            # Convert to RGB for WebP (handles RGBA, palette, etc.)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80, method=4)
            compressed = buf.getvalue()

            # Only use WebP if it's actually smaller
            if len(compressed) < len(file_data):
                logger.info(
                    "Image compressed to WebP: %d -> %d bytes (%.1f%% reduction)",
                    len(file_data),
                    len(compressed),
                    (1 - len(compressed) / len(file_data)) * 100,
                )
                return compressed, True
            return file_data, False

        except Exception:
            logger.warning("Image compression failed, storing original", exc_info=True)
            return file_data, False

    async def get(self, media_id: int) -> Media:
        """Return media metadata."""
        result = await self.db.execute(select(Media).where(Media.id == media_id))
        media = result.scalar_one_or_none()
        if not media:
            raise NotFoundError(f"Media {media_id} not found")
        return media

    async def get_file(self, media_id: int) -> tuple[bytes, str, str]:
        """Return (file_bytes, content_type, filename) from disk.

        Kept for backwards compatibility; prefer :meth:`get_file_path` which
        avoids loading the whole file into memory.
        """
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        content_type = self._content_type_from_ext(media.storage_path, media.media_type)
        # Serve WebP content type for converted images
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return await asyncio.to_thread(full_path.read_bytes), content_type, media.filename

    async def get_file_path(self, media_id: int) -> tuple[Path, str, str]:
        """Return (disk_path, content_type, filename) for streaming.

        Used by the download endpoint so the file is served directly from disk
        with HTTP range support (required for video/audio playback & seeking).
        """
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if not full_path.is_file():
            raise NotFoundError(f"Media file for {media_id} missing on disk")
        content_type = self._content_type_from_ext(media.storage_path, media.media_type)
        if media.storage_path.endswith(".webp"):
            content_type = "image/webp"
        return full_path, content_type, media.filename

    async def delete(self, media_id: int) -> None:
        """Delete media record and remove file from disk."""
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if full_path.exists():
            full_path.unlink()
        await self.db.delete(media)
        await self.db.commit()

    async def list_for_entry(self, entry_id: int) -> list[Media]:
        """Return all media attachments for an entry."""
        result = await self.db.execute(
            select(Media).where(Media.entry_id == entry_id).order_by(Media.created_at)
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        media_type: str | None = None,
    ) -> tuple[list[tuple[Media, str, str | None]], int]:
        """Return all media across non-deleted entries, with entry context.

        Returns list of (media, entry_date_str, entry_title) tuples and total count.
        """
        base_q = (
            select(Media, Entry.entry_date, Entry.title)
            .join(Entry, Media.entry_id == Entry.id)
            .where(Entry.is_deleted == False)  # noqa: E712
        )
        if media_type:
            base_q = base_q.where(Media.media_type == media_type)

        # Total count
        count_q = select(func.count()).select_from(
            select(Media.id)
            .join(Entry, Media.entry_id == Entry.id)
            .where(Entry.is_deleted == False)  # noqa: E712
            .subquery()
        )
        if media_type:
            count_q = select(func.count()).select_from(
                select(Media.id)
                .join(Entry, Media.entry_id == Entry.id)
                .where(Entry.is_deleted == False, Media.media_type == media_type)  # noqa: E712
                .subquery()
            )
        total = (await self.db.execute(count_q)).scalar_one()

        # Paginated results
        rows = await self.db.execute(
            base_q.order_by(Media.created_at.desc()).offset(offset).limit(limit)
        )
        return [(m, str(date), title) for m, date, title in rows.all()], total

    @staticmethod
    def _classify_media(content_type: str) -> str:
        """Map MIME type to media category."""
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"
        return "document"

    @staticmethod
    def _media_content_type(media_type: str) -> str:
        """Return a MIME type hint for the media category.

        Accepts either a bare category ("audio") or a full MIME ("audio/webm")
        so the fallback is always a playable type rather than octet-stream.
        """
        category = media_type.split("/", 1)[0]  # "audio/webm" -> "audio"
        return {"image": "image/jpeg", "video": "video/mp4", "audio": "audio/mpeg"}.get(
            category, "application/octet-stream"
        )

    @staticmethod
    def _content_type_from_ext(storage_path: str, media_type: str) -> str:
        """Return accurate MIME type based on actual file extension.

        ``media_type`` may be either a bare category ("audio") or a full MIME
        ("audio/webm") depending on the upload path, so we normalise to the
        category prefix before mapping. Serving e.g. a .webm recording as
        ``audio/mpeg`` makes browsers refuse to play it, which is the bug this
        guards against.
        """
        ext = storage_path.rsplit(".", 1)[-1].lower() if "." in storage_path else ""
        category = media_type.split("/", 1)[0]  # "audio/webm" -> "audio"
        # Normalise legacy/variant MIME spellings to canonical playable ones.
        if media_type in ("audio/x-wav", "audio/wav", "audio/wave"):
            return "audio/wav"
        audio_map = {
            "webm": "audio/webm",
            "ogg": "audio/ogg",
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "opus": "audio/opus",
        }
        if category == "audio" and ext in audio_map:
            return audio_map[ext]
        return MediaService._media_content_type(media_type)
