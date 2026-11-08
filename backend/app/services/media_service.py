"""Business logic for media attachments."""

import asyncio
import io
import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, MediaSizeError, NotFoundError, ValidationError
from app.models.entry import Entry
from app.models.media import Media
from app.models.note_media import NoteMedia
from app.services import media_crypto

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

# Max dimension for cached timeline thumbnails (see ``get_thumbnail``)
_THUMB_MAX_DIMENSION = 640

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


def ensure_within_media_cap(size: int) -> None:
    """Raise :class:`MediaSizeError` if ``size`` exceeds the per-file media cap."""
    if size > settings.MAX_MEDIA_SIZE_BYTES:
        raise MediaSizeError(f"File exceeds {settings.MAX_MEDIA_SIZE_BYTES} bytes")


async def spool_upload(
    file: UploadFile,
    max_bytes: int,
    *,
    suffix: str = "",
    on_overflow: Callable[[int], Exception] | None = None,
) -> tuple[Path, int]:
    """Stream an ``UploadFile`` to a temp file, enforcing ``max_bytes`` incrementally.

    ``await file.read()`` materialises the whole body in RAM *before* any size
    check runs, so an oversized upload costs memory as well as bandwidth.
    Spooling in 1 MiB chunks aborts the moment the cap is crossed, raising
    whatever ``on_overflow(limit)`` builds (:class:`MediaSizeError` by default;
    the backup/import endpoints pass their own 413 :class:`HTTPException`).

    Returns ``(spool_path, size)``. The caller owns the spool file and must
    unlink it (``spool_path.unlink(missing_ok=True)``).
    """

    def _default_overflow(limit: int) -> Exception:
        return MediaSizeError(f"File exceeds {limit} bytes")

    build_overflow = on_overflow or _default_overflow
    upload = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(upload.name)
    written = 0
    try:
        while True:
            chunk = await file.read(_SPOOL_CHUNK_BYTES)
            if not chunk:
                break
            if written + len(chunk) > max_bytes:
                raise build_overflow(max_bytes)
            upload.write(chunk)
            written += len(chunk)
        upload.flush()
        upload.close()
    except BaseException:
        upload.close()
        path.unlink(missing_ok=True)
        raise
    return path, written


# ``Range: bytes=start-end`` / ``bytes=start-`` / ``bytes=-suffix`` (single range
# only, mirroring Starlette's FileResponse behaviour of serving the whole file
# for anything more exotic).
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


async def media_file_response(
    path: Path,
    storage_path: str,
    content_type: str,
    filename: str,
    range_header: str | None,
) -> Response:
    """Serve a stored media file, decrypting on the fly when it is encrypted.

    Plaintext files go through ``FileResponse`` (zero-copy, native ``Range``
    support — required for video/audio seeking). Encrypted blobs (``LLM1``
    magic, see ``docs/design/media-encryption.md``) cannot use that path: the
    request is answered from the chunked reader instead, decrypting only the
    chunks the range overlaps so seeks stay cheap. A chunk that fails
    authentication maps to **409** — the file itself is never touched.
    """
    encrypted, plaintext_len = await asyncio.to_thread(media_crypto.probe_file, path)
    if not encrypted:
        return FileResponse(
            path=str(path),
            media_type=content_type,
            filename=filename,
            content_disposition_type="inline",
        )

    disposition = _inline_disposition(filename)
    headers = {"Accept-Ranges": "bytes", **disposition}
    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if match:
            start_s, end_s = match.groups()
            if start_s == "" and end_s == "":
                pass  # "bytes=-" is malformed; serve the whole file
            else:
                if start_s == "":
                    # suffix range: last N bytes ("bytes=-0" is unsatisfiable)
                    start = max(0, plaintext_len - int(end_s))
                    length = plaintext_len - start
                else:
                    start = int(start_s)
                    end = int(end_s) if end_s else plaintext_len - 1
                    if start >= plaintext_len or (end_s and end < start):
                        return Response(
                            status_code=416,
                            headers={"Content-Range": f"bytes */{plaintext_len}", **disposition},
                        )
                    length = min(end, plaintext_len - 1) - start + 1
                if length <= 0:
                    return Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{plaintext_len}", **disposition},
                    )
                try:
                    data = await asyncio.to_thread(
                        media_crypto.read_range_file, path, storage_path, start, length
                    )
                except ValueError:
                    logger.warning("Decrypt failed serving %s (range %s)", storage_path, range_header)
                    raise ConflictError(
                        "Attachment cannot be decrypted with this installation's key"
                    ) from None
                return Response(
                    data,
                    status_code=206,
                    media_type=content_type,
                    headers={**headers, "Content-Range": f"bytes {start}-{start + length - 1}/{plaintext_len}"},
                )

    try:
        data = await asyncio.to_thread(
            media_crypto.read_range_file, path, storage_path, 0, plaintext_len
        )
    except ValueError:
        logger.warning("Decrypt failed serving %s", storage_path)
        raise ConflictError(
            "Attachment cannot be decrypted with this installation's key"
        ) from None
    return Response(data, media_type=content_type, headers=headers)


def _inline_disposition(filename: str) -> dict[str, str]:
    """Inline Content-Disposition header, UTF-8 safe (same rules as Starlette)."""
    ascii_name = filename.encode("ascii", "ignore").decode()
    if ascii_name == filename:
        return {"Content-Disposition": f'inline; filename="{filename}"'}
    return {
        "Content-Disposition": f"inline; filename*=utf-8''{quote(filename, safe='')}"
    }


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
        ensure_within_media_cap(size)

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

    async def _require_entry(self, entry_id: int) -> Entry:
        result = await self.db.execute(select(Entry).where(Entry.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found")
        return entry

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
        entry = await self._require_entry(entry_id)

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
        storage_path = f"{media_type}s/{stored_name}"
        full_path = settings.MEDIA_DIR / storage_path
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        file_size = len(final_data)
        if entry.is_encrypted and settings.ENCRYPT_MEDIA:
            # Attachments of encrypted items never touch disk in the clear
            # (docs/design/media-encryption.md §5). file_size records the
            # ciphertext — the bytes actually on disk and in backups.
            final_data = await asyncio.to_thread(media_crypto.encrypt_media, final_data, storage_path)
            file_size = len(final_data)
        await asyncio.to_thread(full_path.write_bytes, final_data)

        return await self._persist_media(
            entry_id,
            safe_name,
            content_type,
            media_type,
            stored_name,
            file_size,
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
        entry = await self._require_entry(entry_id)

        media_type = self._classify_media(content_type)
        final_ext = Path(safe_name).suffix or ".bin"
        convert = content_type in _CONVERTIBLE_IMAGE_TYPES
        final_data = b""
        file_size = size
        encrypt = entry.is_encrypted and settings.ENCRYPT_MEDIA
        if convert:
            # Images must be re-encoded anyway, so read + compress off-loop.
            data = await asyncio.to_thread(src.read_bytes)
            final_data, converted = await asyncio.to_thread(MediaService._compress_to_webp, data)
            if converted:
                final_ext = ".webp"
            file_size = len(final_data)

        stored_name = f"{uuid.uuid4()}{final_ext}"
        storage_path = f"{media_type}s/{stored_name}"
        full_path = settings.MEDIA_DIR / storage_path
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        if encrypt:
            if not convert:
                final_data = await asyncio.to_thread(src.read_bytes)
            final_data = await asyncio.to_thread(media_crypto.encrypt_media, final_data, storage_path)
            file_size = len(final_data)
            await asyncio.to_thread(full_path.write_bytes, final_data)
        elif convert:
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
        data = await asyncio.to_thread(full_path.read_bytes)
        if media_crypto.looks_encrypted(data):
            # In-memory decrypt (OCR path); never writes a plaintext temp file.
            data = await asyncio.to_thread(
                media_crypto.decrypt_media, data, media.storage_path
            )
        return data, content_type, media.filename

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

    @staticmethod
    def _thumb_path_for(media: Media | NoteMedia, *, encrypted: bool = False) -> Path:
        name = f"{media.media_type}-{Path(media.storage_path).name}.webp"
        if encrypted:
            name += ".llm1"
        return settings.MEDIA_DIR / "thumbs" / name

    async def get_thumbnail(self, media_id: int) -> tuple[Path | bytes, str]:
        """Return (thumb_path_or_bytes, content_type) for an image, generating on demand.

        The first request renders a ≤640px WebP next to the original and caches
        it on disk; later requests serve the cached file. Timeline grids load
        dozens of images per page — serving full originals there decoded
        gigabytes in WebKit and OOM-killed the machine (2026-10-27).

        For an encrypted source (or an encrypted parent entry) the cache is an
        encrypted ``.webp.llm1`` sibling and this returns **decrypted bytes** —
        a plaintext WebP of a sensitive image must never exist on disk
        (docs/design/media-encryption.md §4).
        """
        media = await self.get(media_id)
        if media.media_type != "image":
            raise NotFoundError(f"Media {media_id} is not an image")
        full_path = settings.MEDIA_DIR / media.storage_path
        if not full_path.is_file():
            raise NotFoundError(f"Media file for {media_id} missing on disk")

        # Cache flavour follows the **blob**, not the parent flag: after the
        # migration every encrypted parent's blob is encrypted, and while a
        # legacy plaintext blob exists its plaintext thumb leaks nothing the
        # blob doesn't already. This keeps one query off the hot grid path.
        encrypted, _plain_len = await asyncio.to_thread(media_crypto.probe_file, full_path)
        use_encrypted_cache = encrypted

        thumb_path = self._thumb_path_for(media)
        enc_path = self._thumb_path_for(media, encrypted=True)
        content_type = self._content_type_from_ext(media.storage_path, media.media_type)

        if not use_encrypted_cache:
            if not thumb_path.is_file():
                try:
                    await asyncio.to_thread(self._write_thumbnail, full_path, thumb_path)
                except Exception:
                    # A corrupt/undecodable image must never 500 the timeline grid —
                    # fall back to streaming the original instead.
                    logger.warning("Thumbnail generation failed for media %s", media_id, exc_info=True)
                    return full_path, content_type
            return thumb_path, "image/webp"

        # Encrypted cache: serve decrypted bytes from the sibling if present.
        enc_storage_path = self._rel_path(enc_path)
        if not enc_path.is_file():
            try:
                source = await asyncio.to_thread(
                    self._read_stored_bytes, full_path, media.storage_path
                )
                await asyncio.to_thread(
                    MediaService._write_thumbnail_encrypted,
                    source,
                    enc_path,
                    enc_storage_path,
                )
                # A stale plaintext WebP must not survive next to the cache.
                thumb_path.unlink(missing_ok=True)
            except ConflictError:
                raise
            except Exception:
                logger.warning("Thumbnail generation failed for media %s", media_id, exc_info=True)
                # Fall back to the decrypted original rather than a blank tile.
                try:
                    data = await asyncio.to_thread(
                        self._read_stored_bytes, full_path, media.storage_path
                    )
                except ValueError:
                    raise ConflictError(
                        "Attachment cannot be decrypted with this installation's key"
                    ) from None
                return data, content_type
        cached = await asyncio.to_thread(enc_path.read_bytes)
        try:
            data = await asyncio.to_thread(media_crypto.decrypt_media, cached, enc_storage_path)
        except ValueError:
            raise ConflictError(
                "Attachment cannot be decrypted with this installation's key"
            ) from None
        return data, "image/webp"

    def _rel_path(self, path: Path) -> str:
        """Path relative to MEDIA_DIR — the AAD identity used at encryption time."""
        return str(path.relative_to(settings.MEDIA_DIR)).replace(os.sep, "/")

    @staticmethod
    def _read_stored_bytes(full_path: Path, storage_path: str) -> bytes:
        """Read a stored blob, decrypting when it parses as an encrypted blob."""
        data = full_path.read_bytes()
        if media_crypto.looks_encrypted(data):
            data = media_crypto.decrypt_media(data, storage_path)
        return data

    @staticmethod
    def _write_thumbnail(full_path: Path, thumb_path: Path) -> None:
        """Render a ≤640px WebP thumb from a plaintext file, atomically placed."""
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = MediaService._render_thumbnail_bytes(full_path.read_bytes())
        MediaService._atomic_write(thumb_path, rendered)

    @staticmethod
    def _write_thumbnail_encrypted(
        source_bytes: bytes, thumb_path: Path, thumb_storage_path: str
    ) -> None:
        """Render + encrypt a thumb from decrypted source bytes, atomically placed.

        The rendered WebP is encrypted with the **thumb's own** storage path as
        AAD before it touches disk (design §4's ``<hash>.webp.llm1`` sibling).
        """
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = MediaService._render_thumbnail_bytes(source_bytes)
        blob = media_crypto.encrypt_media(rendered, thumb_storage_path)
        MediaService._atomic_write(thumb_path, blob)

    @staticmethod
    def _render_thumbnail_bytes(source_bytes: bytes) -> bytes:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(source_bytes)) as source:
            img: Image.Image = source
            if hasattr(img, "transpose"):
                img = ImageOps.exif_transpose(img)
            if max(img.size) > _THUMB_MAX_DIMENSION:
                resampling = getattr(Image, "Resampling", Image)
                img.thumbnail((_THUMB_MAX_DIMENSION, _THUMB_MAX_DIMENSION), resampling.LANCZOS)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80, method=4)
            return buf.getvalue()

    @staticmethod
    def _atomic_write(thumb_path: Path, data: bytes) -> None:
        # Write to a unique temp name then rename: two concurrent first
        # requests must not see each other's half-written file.
        tmp = thumb_path.with_name(f".{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(thumb_path)
        finally:
            tmp.unlink(missing_ok=True)

    async def delete(self, media_id: int) -> None:
        """Delete media record and remove file from disk."""
        media = await self.get(media_id)
        full_path = settings.MEDIA_DIR / media.storage_path
        if full_path.exists():
            full_path.unlink()
        # Both cache flavours: the plaintext WebP and the encrypted .llm1
        # sibling — leaving the latter would orphan ciphertext on disk forever.
        self._thumb_path_for(media).unlink(missing_ok=True)
        self._thumb_path_for(media, encrypted=True).unlink(missing_ok=True)
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
