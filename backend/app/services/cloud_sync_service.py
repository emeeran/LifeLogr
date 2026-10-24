"""Cloud sync service — E2E encrypted sync with provider adapters."""

from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from pathlib import Path
from typing import IO, Any, Awaitable, Callable, Protocol
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import SyncQueue, SyncStatus

logger = logging.getLogger(__name__)

# Chunk size for streaming provider transfers (1 MiB).
_DOWNLOAD_CHUNK = 1024 * 1024
_DAV_NS = "DAV:"

# Above this size a first-time Google Drive upload switches from the buffered
# multipart create to a resumable (streamed) upload. Small payloads — the
# individual sync op files — are simpler and cheaper to send in one multipart
# request; backup archives are the ones that must never be held in memory.
_RESUMABLE_UPLOAD_MIN_BYTES = 8 * 1024 * 1024


def _file_byte_stream(path: str | Path, chunk_size: int = _DOWNLOAD_CHUNK) -> AsyncIterator[bytes]:
    """Stream *path* in chunks as an async iterator, for httpx request bodies.

    ``httpx.AsyncClient`` refuses a plain (blocking) file handle as ``content``
    — it raises "Attempted to send an sync request with an AsyncClient
    instance" — so the reads happen in a thread and surface as an async stream.
    Used both for uploads (an archive is streamed up, never buffered) and,
    inverted, for downloads.
    """

    async def _stream() -> AsyncIterator[bytes]:
        fh = await asyncio.to_thread(open, str(path), "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(fh.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(fh.close)

    return _stream()


# ── WebDAV PROPFIND helpers ────────────────────────────────────────────


def _dav_root_path(base_url: str, username: str) -> str:
    """Root path of the user's DAV files collection, with a trailing slash.

    Keeps any sub-path baked into *base_url* (e.g. ``https://host/nextcloud``),
    so hrefs can be made relative to the same root the upload/download/delete
    paths are expressed against.
    """
    base = urlsplit(base_url).path.rstrip("/")
    return f"{base}/remote.php/dav/files/{username}/"


def _multistatus_paths(body: bytes, root_path: str, prefix: str) -> list[str]:
    """Extract clean, root-relative paths from a WebDAV 207 multistatus body.

    Namespace-aware parse of the ``DAV:`` multistatus document (the previous
    substring scan returned raw XML fragments, which no caller could use).
    Returns URL-decoded paths relative to *root_path* so they line up with the
    paths ``upload_file``/``download``/``delete`` take, filtered to *prefix*.
    The root collection itself is skipped.
    """
    try:
        tree = ET.fromstring(body)
    except ET.ParseError:
        logger.warning("WebDAV PROPFIND body was not parseable XML; treating as empty")
        return []

    found: list[str] = []
    for response in tree.findall(f"{{{_DAV_NS}}}response"):
        href = response.find(f"{{{_DAV_NS}}}href")
        if href is None or not href.text:
            continue
        raw = unquote(href.text)
        path = urlsplit(raw).path if "://" in raw else raw
        if not path.startswith(root_path):
            continue
        rel = path[len(root_path) :].rstrip("/")
        if rel and rel.startswith(prefix):
            found.append(rel)
    return found


# ── Sync queue helpers (inlined from sync_service.py) ──────────────────

# Entity types the pull/merge path can actually apply. Enqueue validates against
# this so an operation is either merged on pull or never queued at all — the
# queue used to accept anything and silently drop it on pull.
#
# ``tag`` is deliberately excluded: tags are not independent synced state. They
# live in the entry/note body text as ``#hashtags`` (``services/hashtag.py``)
# and are re-derived from the body on every save — client-sent tag ids are
# ignored by design — so a queued tag op would be a no-op on pull.
#
# ``media`` is deliberately excluded: sync ops are JSON payloads on the cloud
# provider, and the binary blob a media row points at is never transferred by
# this channel, so applying the op would create a row whose file does not exist
# on the pulling machine. Media travels with full backup/restore instead.
SYNCABLE_ENTITY_TYPES = ("entry", "note")


class UnsupportedSyncEntityType(ValueError):
    """Raised when an enqueue asks to sync an entity type we cannot merge."""


def ensure_syncable_entity_type(entity_type: str) -> str:
    """Return *entity_type* if it is mergeable, else raise.

    Keeps the queue and the pull path in agreement: everything enqueued here
    has an ``_apply_*_op`` implementation in :class:`CloudSyncService`.
    """
    if entity_type not in SYNCABLE_ENTITY_TYPES:
        raise UnsupportedSyncEntityType(
            f"entity_type {entity_type!r} cannot be synced. Syncable types: "
            f"{', '.join(SYNCABLE_ENTITY_TYPES)}. Tags are derived from "
            "#hashtags in the entry/note body (client-sent tag ids are ignored), "
            "and media blobs travel with backup/restore, not the op channel."
        )
    return entity_type


class SyncService:
    """Offline queue, flush, and conflict resolution."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue(
        self, operation: str, entity_type: str, entity_id: int, payload: dict[str, object]
    ) -> SyncQueue:
        """Queue an operation for later sync.

        Raises :class:`UnsupportedSyncEntityType` for entity types the pull
        merge cannot apply, so nothing is queued that pull would silently drop.
        """
        ensure_syncable_entity_type(entity_type)
        item = SyncQueue(
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.dumps(payload),
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get_pending(self, limit: int = 100) -> list[SyncQueue]:
        """Return unsynced operations."""
        result = await self.db.execute(
            select(SyncQueue)
            .where(SyncQueue.is_synced == False)  # noqa: E712
            .order_by(SyncQueue.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_pending_count(self) -> int:
        """Count unsynced operations."""
        result = await self.db.execute(
            select(func.count()).select_from(SyncQueue).where(SyncQueue.is_synced == False)  # noqa: E712
        )
        return result.scalar_one()

    async def flush(self, provider: str = "local") -> dict[str, int | str]:
        """Mark all pending operations as synced."""
        pending = await self.get_pending()
        now = datetime.now(timezone.utc)
        for item in pending:
            item.is_synced = True
            item.synced_at = now

        status = await self._get_or_create_status(provider)
        status.last_sync_at = now
        status.status = "idle"
        status.error_message = None

        await self.db.commit()
        return {"synced": len(pending), "provider": provider}

    async def get_status(self, provider: str = "local") -> SyncStatus:
        """Get sync status for a provider."""
        return await self._get_or_create_status(provider)

    async def _get_or_create_status(self, provider: str) -> SyncStatus:
        result = await self.db.execute(select(SyncStatus).where(SyncStatus.provider == provider))
        status = result.scalar_one_or_none()
        if not status:
            status = SyncStatus(provider=provider)
            self.db.add(status)
            await self.db.flush()
        return status


# ── Provider protocol ──────────────────────────────────────────────────


class SyncProvider(Protocol):
    """Interface for cloud sync providers."""

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str: ...

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str: ...
    async def download(self, path: str) -> bytes: ...

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream *path* from the provider straight into *local_path*.

        Backup archives can be gigabytes, so restores must never buffer a whole
        download in memory — implementations write in chunks and return *path*.
        """
        ...

    async def list_files(self, prefix: str) -> list[str]: ...
    async def delete(self, path: str) -> None: ...
    async def close(self) -> None: ...


# ── Local filesystem provider ──────────────────────────────────────────


class LocalFileProvider:
    """Local filesystem sync provider (for testing/dev)."""

    def __init__(self, base_dir: str = "/tmp/lifelogr-sync") -> None:
        self._base = Path(base_dir)

    def _safe_target(self, path: str) -> Path:
        """Resolve ``path`` under the base dir, rejecting traversal escapes."""
        target = (self._base / path).resolve()
        try:
            target.relative_to(self._base.resolve())
        except ValueError:
            raise ValueError(f"Path escapes sync base: {path}") from None
        return target

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        target = self._safe_target(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file into place (disk-to-disk; no full in-memory copy)."""
        import shutil

        target = self._base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return str(target)

    async def download(self, path: str) -> bytes:
        target = self._safe_target(path)
        return target.read_bytes()

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a local provider file to disk (disk-to-disk copy)."""
        import shutil

        target = self._safe_target(path)
        with open(target, "rb") as src, open(local_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return path

    async def list_files(self, prefix: str) -> list[str]:
        if not self._base.exists():
            return []
        return [
            str(p.relative_to(self._base)) for p in self._base.rglob(f"{prefix}*") if p.is_file()
        ]

    async def delete(self, path: str) -> None:
        target = self._safe_target(path)
        if target.exists():
            target.unlink()

    async def close(self) -> None:
        """Local provider has no open resources."""
        return None


# ── Nextcloud (WebDAV) provider ────────────────────────────────────────


class NextcloudProvider:
    """Nextcloud WebDAV sync provider with a shared httpx client."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._url = base_url.rstrip("/")
        self._auth = (username, password)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        client = self._get_client()
        resp = await client.put(
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
            content=data,
            auth=self._auth,
        )
        resp.raise_for_status()
        return path

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file to WebDAV (body read in chunks, not buffered)."""
        client = self._get_client()
        resp = await client.put(
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
            content=_file_byte_stream(local_path),
            auth=self._auth,
            timeout=300.0,
        )
        resp.raise_for_status()
        return path

    async def download(self, path: str) -> bytes:
        client = self._get_client()
        resp = await client.get(
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
            auth=self._auth,
        )
        resp.raise_for_status()
        return resp.content

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a WebDAV download to *local_path* in chunks (never buffered)."""
        client = self._get_client()
        with open(local_path, "wb") as fh:
            async with client.stream(
                "GET",
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
                auth=self._auth,
                timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    fh.write(chunk)
        return path

    async def list_files(self, prefix: str) -> list[str]:
        client = self._get_client()
        resp = await client.request(
            "PROPFIND",
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/",
            auth=self._auth,
            headers={"Depth": "1"},
        )
        if resp.status_code != 207:
            return []
        return _multistatus_paths(
            resp.content, _dav_root_path(self._url, self._auth[0]), prefix
        )

    async def delete(self, path: str) -> None:
        client = self._get_client()
        resp = await client.delete(
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
            auth=self._auth,
        )
        resp.raise_for_status()

    async def close(self) -> None:
        """Safely release connection resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("Nextcloud provider HTTP client closed.")


# ── Google Drive provider ──────────────────────────────────────────────


class _OAuthProviderBase:
    """Shared OAuth-provider HTTP-client lifecycle.

    Each concrete provider (Google Drive / OneDrive / Dropbox / Box) keeps its
    own token-refresh logic — Box rotates its refresh token and uses a 3-arg
    callback; OneDrive sends a scope — so refresh stays per-subclass. Only the
    identical lazy HTTP-client helper lives here, deduped from four copies.
    """

    _client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client


class GoogleDriveProvider(_OAuthProviderBase):
    """Google Drive sync provider with a shared httpx client.

    Backups are stored in a visible ``LifeLogr Backups`` folder in My Drive
    (scope ``drive.file``). A residual ``drive.appdata`` scope is retained so
    the hidden App Data folder can still be read when migrating older backups.
    """

    BACKUP_FOLDER_NAME = "LifeLogr Backups"

    def __init__(
        self,
        credentials: dict[str, str],
        on_token_refresh: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")
        self._on_token_refresh = on_token_refresh
        self._client: httpx.AsyncClient | None = None
        self._folder_id: str | None = None

    async def _ensure_valid_token(self) -> str:
        """Refreshes the access token if expired or missing."""
        import time

        now = time.time()
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token

        if not self._refresh_token:
            raise ValueError("Refresh token missing from Google Drive credentials")
        if not self._client_id or not self._client_secret:
            raise ValueError("Google OAuth client credentials are not configured")

        client = self._get_client()
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        self._token_expiry = str(now + data["expires_in"])

        if self._on_token_refresh:
            await self._on_token_refresh(self._access_token, self._token_expiry)

        return self._access_token

    async def _get_backup_folder(self) -> str:
        """Find or create the visible ``LifeLogr Backups`` folder in My Drive.

        Backups live here (not the hidden App Data folder) so they are visible
        and browsable in drive.google.com. The folder ID is cached per instance.
        """
        if self._folder_id:
            return self._folder_id
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        headers = {"Authorization": f"Bearer {token}"}
        client = self._get_client()

        # No 'root' in parents clause: under drive.file the listing is already
        # scoped to files this app created, and that clause can raise 403.
        query = (
            "mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{self.BACKUP_FOLDER_NAME}' and trashed = false"
        )
        resp = await client.get(
            f"https://www.googleapis.com/drive/v3/files?q={quote(query)}",
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        files = resp.json().get("files", [])
        if files:
            self._folder_id = files[0]["id"]
            return self._folder_id

        # Not found — create it in My Drive root.
        resp = await client.post(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            json={
                "name": self.BACKUP_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        self._folder_id = resp.json()["id"]
        logger.info("Created Google Drive backup folder '%s'.", self.BACKUP_FOLDER_NAME)
        return self._folder_id

    async def _get_folder_or_appdata(self) -> str:
        """Return the visible folder id, or ``"appDataFolder"`` as a fallback.

        A ``drive.appdata``-only token (a re-link that didn't revoke the old
        grant first) cannot access My Drive, so the visible-folder query 403s.
        Rather than fail the whole backup, degrade to the hidden App Data
        folder — backups still succeed; ``last_location`` records which.
        """
        if getattr(self, "_use_appdata", False):
            return "appDataFolder"
        try:
            return await self._get_backup_folder()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning(
                    "Google Drive token lacks drive.file scope — falling back to "
                    "hidden App Data. Re-link (revoke the old grant first at "
                    "myaccount.google.com/permissions) for a visible folder."
                )
                self._use_appdata = True
                return "appDataFolder"
            raise

    async def _query_files(self, query: str, *, spaces: str = "") -> list[dict[str, Any]]:
        """Run a Drive files.list query and return the raw file dicts."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}"
        if spaces:
            url += f"&spaces={spaces}"
        client = self._get_client()
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        resp.raise_for_status()
        files: list[dict[str, Any]] = resp.json().get("files", [])
        return files

    async def _find_file_id(self, path: str, *, look_in: str = "folder") -> str | None:
        """Find the Drive file ID for *path* in the backup folder or App Data."""
        parent = await self._get_backup_folder() if look_in == "folder" else "appDataFolder"
        query = f"name = '{path}' and '{parent}' in parents and trashed = false"
        spaces = "appDataFolder" if look_in == "appdata" else ""
        files = await self._query_files(query, spaces=spaces)
        return files[0]["id"] if files else None

    async def _create_in_folder(self, name: str, data: bytes, folder_id: str) -> None:
        """Create a new file inside *folder_id* via a multipart upload."""
        import json as _json

        token = await self._ensure_valid_token()
        client = self._get_client()
        boundary = b"lifelogr_upload_boundary"
        resp = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary.decode()}",
            },
            content=(
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                + _json.dumps({"name": name, "parents": [folder_id]}).encode("utf-8")
                + b"\r\n"
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n"
                b"--" + boundary + b"--\r\n"
            ),
            timeout=15.0,
        )
        resp.raise_for_status()

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        token = await self._ensure_valid_token()
        parent = await self._get_folder_or_appdata()
        look_in = "appdata" if parent == "appDataFolder" else "folder"
        file_id = await self._find_file_id(path, look_in=look_in)
        client = self._get_client()

        if file_id:
            # Update the existing file in place.
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            resp = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                },
                content=data,
                timeout=15.0,
            )
            resp.raise_for_status()
            self.last_location = look_in
            return path

        await self._create_in_folder(path, data, parent)
        self.last_location = look_in
        return path

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file to Google Drive.

        Existing files are updated with a streaming media PATCH. A first-ever
        backup for a name has no file to patch, so it is *created* — with a
        resumable (``uploadType=resumable``) upload that streams from disk once
        the archive is big enough to matter, and the buffered multipart create
        for the small ones.
        """

        token = await self._ensure_valid_token()
        parent = await self._get_folder_or_appdata()
        look_in = "appdata" if parent == "appDataFolder" else "folder"
        file_id = await self._find_file_id(path, look_in=look_in)
        client = self._get_client()
        if file_id:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            resp = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                },
                content=_file_byte_stream(local_path),
                timeout=300.0,
            )
            resp.raise_for_status()
            self.last_location = look_in
            return path
        if Path(local_path).stat().st_size >= _RESUMABLE_UPLOAD_MIN_BYTES:
            await self._create_resumable_in_folder(path, local_path, parent)
        else:
            await self._create_in_folder(path, Path(local_path).read_bytes(), parent)
        self.last_location = look_in
        return path

    async def _create_resumable_in_folder(self, name: str, local_path: str, folder_id: str) -> None:
        """Create *name* in *folder_id* via a resumable upload streamed from disk.

        Two requests: a metadata POST that yields a session URI (with the total
        size declared up front), then a single PUT that streams the file into
        it — so a multi-gigabyte archive never has to be held in memory.
        """
        import os

        token = await self._ensure_valid_token()
        client = self._get_client()
        size = os.path.getsize(local_path)
        resp = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Upload-Content-Type": "application/octet-stream",
                "X-Upload-Content-Length": str(size),
            },
            json={"name": name, "parents": [folder_id]},
            timeout=15.0,
        )
        resp.raise_for_status()
        session_uri = resp.headers.get("Location")
        if not session_uri:
            raise ValueError("Google Drive resumable upload returned no session URI")
        upload = await client.put(
            session_uri,
            headers={"Content-Length": str(size)},
            content=_file_byte_stream(local_path),
            timeout=300.0,
        )
        upload.raise_for_status()

    async def _download_by_id(self, file_id: str) -> bytes:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.content

    async def _download_by_id_to_file(self, file_id: str, local_path: str) -> None:
        token = await self._ensure_valid_token()
        client = self._get_client()
        with open(local_path, "wb") as fh:
            async with client.stream(
                "GET",
                f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
                headers={"Authorization": f"Bearer {token}"},
                timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    fh.write(chunk)

    async def download(self, path: str) -> bytes:
        # Visible folder first, then legacy App Data for unmigrated backups.
        return await self._download_by_id(await self._require_file_id(path))

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a Drive download to *local_path* (archives can be gigabytes)."""
        await self._download_by_id_to_file(await self._require_file_id(path), local_path)
        return path

    async def _require_file_id(self, path: str) -> str:
        """Resolve *path* to a Drive file id, raising if it is not there.

        Visible folder first, then legacy App Data for unmigrated backups.
        """
        file_id = await self._find_file_id(path, look_in="folder")
        if not file_id:
            file_id = await self._find_file_id(path, look_in="appdata")
        if not file_id:
            raise FileNotFoundError(f"File not found on Google Drive: {path}")
        return file_id

    async def _list_names(self, prefix: str, *, look_in: str = "folder") -> list[str]:
        parent = await self._get_backup_folder() if look_in == "folder" else "appDataFolder"
        query = f"name contains '{prefix}' and '{parent}' in parents and trashed = false"
        spaces = "appDataFolder" if look_in == "appdata" else ""
        files = await self._query_files(query, spaces=spaces)
        return [f["name"] for f in files]

    async def list_files(self, prefix: str) -> list[str]:
        """List backups in the visible folder plus any still in App Data."""
        names: set[str] = set()
        try:
            names.update(await self._list_names(prefix, look_in="folder"))
        except Exception:
            logger.debug("list_files(folder) failed", exc_info=True)
        try:
            names.update(await self._list_names(prefix, look_in="appdata"))
        except Exception:
            logger.debug("list_files(appdata) failed", exc_info=True)
        return sorted(names)

    async def _delete_by_id(self, file_id: str) -> None:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        resp.raise_for_status()

    async def delete(self, path: str) -> None:
        file_id = await self._find_file_id(path, look_in="folder")
        if not file_id:
            file_id = await self._find_file_id(path, look_in="appdata")
        if file_id:
            await self._delete_by_id(file_id)

    async def migrate_appdata_backups(self) -> int:
        """Move backups stranded in the hidden App Data folder into the visible
        ``LifeLogr Backups`` folder, then remove the originals. Idempotent.

        Requires the ``drive.appdata`` scope (to read the old location) and
        ``drive.file`` (to write the new one). Best-effort: failures log and
        skip, so a partial migration is retried on the next run.
        """
        try:
            legacy = await self._list_names("lifelogr-backup-", look_in="appdata")
        except Exception:
            logger.debug("migrate: could not list App Data backups", exc_info=True)
            return 0

        folder_id = await self._get_backup_folder()
        moved = 0
        for name in legacy:
            try:
                if await self._find_file_id(name, look_in="folder"):
                    continue  # already migrated
                old_id = await self._find_file_id(name, look_in="appdata")
                if not old_id:
                    continue
                await self._create_in_folder(name, await self._download_by_id(old_id), folder_id)
                await self._delete_by_id(old_id)
                moved += 1
            except Exception:
                logger.warning("Failed to migrate backup '%s' from App Data", name, exc_info=True)

        if moved:
            logger.info("Migrated %d backup(s) from App Data to the visible folder.", moved)
        return moved

    async def close(self) -> None:
        """Safely release connection resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("Google Drive provider HTTP client closed.")


# ── OneDrive (Microsoft Graph app folder) provider ─────────────────────


class OneDriveProvider(_OAuthProviderBase):
    """OneDrive sync provider via the Microsoft Graph API (app root folder)."""

    GRAPH = "https://graph.microsoft.com/v1.0/me/drive/special/approot"
    TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(
        self,
        credentials: dict[str, str],
        on_token_refresh: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")
        self._on_token_refresh = on_token_refresh
        self._client: httpx.AsyncClient | None = None

    async def _ensure_valid_token(self) -> str:
        import time

        now = time.time()
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token
        if not self._refresh_token:
            raise ValueError("Refresh token missing from OneDrive credentials")
        if not self._client_id or not self._client_secret:
            raise ValueError("OneDrive OAuth client credentials are not configured")

        client = self._get_client()
        resp = await client.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
                "scope": "Files.ReadWrite.AppFolder offline_access",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = str(now + data["expires_in"])
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]  # OneDrive may rotate it
        if self._on_token_refresh:
            await self._on_token_refresh(self._access_token, self._token_expiry)
        return self._access_token

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.put(
            f"{self.GRAPH}:{quote(path)}:/content",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            content=data,
            timeout=30.0,
        )
        resp.raise_for_status()
        return path

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file to OneDrive (body read in chunks, not buffered)."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.put(
            f"{self.GRAPH}:{quote(path)}:/content",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            content=_file_byte_stream(local_path),
            timeout=300.0,
        )
        resp.raise_for_status()
        return path

    async def download(self, path: str) -> bytes:
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.get(
            f"{self.GRAPH}:{quote(path)}:/content",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.content

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a Graph download to *local_path* in chunks."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        with open(local_path, "wb") as fh:
            async with client.stream(
                "GET",
                f"{self.GRAPH}:{quote(path)}:/content",
                headers={"Authorization": f"Bearer {token}"},
                timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    fh.write(chunk)
        return path

    async def list_files(self, prefix: str) -> list[str]:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.get(
            f"{self.GRAPH}/children?$select=name",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        names = [v.get("name", "") for v in resp.json().get("value", [])]
        return [n for n in names if n.startswith(prefix)]

    async def delete(self, path: str) -> None:
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.delete(
            f"{self.GRAPH}:{quote(path)}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        resp.raise_for_status()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("OneDrive provider HTTP client closed.")


# ── Dropbox provider ───────────────────────────────────────────────────


class DropboxProvider(_OAuthProviderBase):
    """Dropbox sync provider via the Dropbox API (offline token refresh)."""

    TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
    API = "https://api.dropboxapi.com/2"
    CONTENT = "https://content.dropboxapi.com/2"

    def __init__(
        self,
        credentials: dict[str, str],
        on_token_refresh: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")
        self._on_token_refresh = on_token_refresh
        self._client: httpx.AsyncClient | None = None

    async def _ensure_valid_token(self) -> str:
        import time

        now = time.time()
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token
        if not self._refresh_token or not self._client_id or not self._client_secret:
            raise ValueError("Dropbox OAuth client credentials / refresh token not configured")

        client = self._get_client()
        resp = await client.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = str(now + data["expires_in"])
        if self._on_token_refresh:
            await self._on_token_refresh(self._access_token, self._token_expiry)
        return self._access_token

    def _api_arg(self, path: str, **extra: object) -> str:
        import json as _json

        return _json.dumps({"path": f"/{path}", **extra})

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.post(
            f"{self.CONTENT}/files/upload",
            headers={
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": self._api_arg(path, mode="overwrite"),
                "Content-Type": "application/octet-stream",
            },
            content=data,
            timeout=30.0,
        )
        resp.raise_for_status()
        return path

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file to Dropbox (body read in chunks, not buffered)."""
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.post(
            f"{self.CONTENT}/files/upload",
            headers={
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": self._api_arg(path, mode="overwrite"),
                "Content-Type": "application/octet-stream",
            },
            content=_file_byte_stream(local_path),
            timeout=300.0,
        )
        resp.raise_for_status()
        return path

    async def download(self, path: str) -> bytes:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.post(
            f"{self.CONTENT}/files/download",
            headers={"Authorization": f"Bearer {token}", "Dropbox-API-Arg": self._api_arg(path)},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.content

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a Dropbox download to *local_path* in chunks."""
        token = await self._ensure_valid_token()
        client = self._get_client()
        with open(local_path, "wb") as fh:
            async with client.stream(
                "POST",
                f"{self.CONTENT}/files/download",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Dropbox-API-Arg": self._api_arg(path),
                },
                timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    fh.write(chunk)
        return path

    async def list_files(self, prefix: str) -> list[str]:
        import json as _json

        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.post(
            f"{self.API}/files/list_folder",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=_json.dumps({"path": "", "recursive": True}),
            timeout=15.0,
        )
        resp.raise_for_status()
        names = [
            e.get("name", "") for e in resp.json().get("entries", []) if e.get(".tag") == "file"
        ]
        return [n for n in names if n.startswith(prefix)]

    async def delete(self, path: str) -> None:
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.post(
            f"{self.API}/files/delete_v2",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=self._api_arg(path),
            timeout=10.0,
        )
        resp.raise_for_status()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("Dropbox provider HTTP client closed.")


# ── Box provider ────────────────────────────────────────────────────────


class BoxProvider(_OAuthProviderBase):
    """Box sync provider via the Box Content API (LifeLogr folder in root).

    Raw httpx — mirrors OneDriveProvider. Box **rotates** its refresh token on
    each refresh, so ``on_token_refresh`` is 3-arg ``(access, refresh, expiry)``
    and the caller must persist the new refresh token.
    """

    AUTHORIZE_URL = "https://account.box.com/api/oauth2/authorize"
    TOKEN_URL = "https://api.box.com/oauth2/token"
    API = "https://api.box.com/2.0"
    UPLOAD_API = "https://upload.box.com/api/2.0"
    ROOT_FOLDER_ID = "0"
    FOLDER_NAME = "LifeLogr"

    def __init__(
        self,
        credentials: dict[str, str],
        on_token_refresh: Callable[[str, str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")
        self._on_token_refresh = on_token_refresh
        self._client: httpx.AsyncClient | None = None
        self._folder_id: str | None = None

    async def _ensure_valid_token(self) -> str:
        import time

        now = time.time()
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token
        if not self._refresh_token:
            raise ValueError("Refresh token missing from Box credentials")
        if not self._client_id or not self._client_secret:
            raise ValueError("Box OAuth client credentials are not configured")

        client = self._get_client()
        resp = await client.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = str(now + data["expires_in"])
        # Box rotates the refresh token — keep the new one or the next refresh fails.
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]
        if self._on_token_refresh:
            await self._on_token_refresh(
                self._access_token, self._refresh_token or "", self._token_expiry
            )
        return self._access_token

    async def _get_folder_id(self) -> str:
        """Find (or create) the LifeLogr folder under the Box root."""
        if self._folder_id:
            return self._folder_id
        token = await self._ensure_valid_token()
        client = self._get_client()
        resp = await client.get(
            f"{self.API}/folders/{self.ROOT_FOLDER_ID}/items",
            params={"fields": "type,id,name", "limit": 1000},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        for entry in resp.json().get("entries", []):
            if entry.get("type") == "folder" and entry.get("name") == self.FOLDER_NAME:
                self._folder_id = entry["id"]
                return self._folder_id
        resp = await client.post(
            f"{self.API}/folders",
            json={"name": self.FOLDER_NAME, "parent": {"id": self.ROOT_FOLDER_ID}},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        self._folder_id = resp.json()["id"]
        return self._folder_id

    async def _file_id(self, name: str) -> str:
        token = await self._ensure_valid_token()
        folder_id = await self._get_folder_id()
        client = self._get_client()
        resp = await client.get(
            f"{self.API}/folders/{folder_id}/items",
            params={"fields": "type,id,name", "limit": 1000},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        entries: list[dict[str, Any]] = resp.json().get("entries", [])
        for entry in entries:
            if entry.get("type") == "file" and entry.get("name") == name:
                file_id: str = entry["id"]
                return file_id
        raise ValueError(f"File '{name}' not found in Box folder")

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        token = await self._ensure_valid_token()
        folder_id = await self._get_folder_id()
        client = self._get_client()
        # Box file upload is multipart: an `attributes` JSON field + the file.
        # Value type widened so the dict conforms to httpx's RequestFiles union.
        files: dict[
            str, tuple[str | None, bytes | str] | tuple[str | None, bytes | str, str | None]
        ] = {
            "attributes": (None, json.dumps({"name": path, "parent": {"id": folder_id}})),
            "file": (path, data),
        }
        resp = await client.post(
            f"{self.UPLOAD_API}/files/content",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            timeout=120.0,
        )
        resp.raise_for_status()
        return path

    async def upload_file(self, path: str, local_path: str, encrypted: bool = False) -> str:
        """Stream a local file to Box via multipart (file streamed, not buffered)."""
        token = await self._ensure_valid_token()
        folder_id = await self._get_folder_id()
        client = self._get_client()
        fh = open(local_path, "rb")
        files: dict[
            str, tuple[str | None, bytes | str] | tuple[str | None, bytes | IO[bytes], str | None]
        ] = {
            "attributes": (None, json.dumps({"name": path, "parent": {"id": folder_id}})),
            "file": (path, fh, "application/octet-stream"),
        }
        try:
            resp = await client.post(
                f"{self.UPLOAD_API}/files/content",
                headers={"Authorization": f"Bearer {token}"},
                files=files,
                timeout=300.0,
            )
        finally:
            fh.close()
        resp.raise_for_status()
        return path

    async def list_files(self, prefix: str) -> list[str]:
        token = await self._ensure_valid_token()
        folder_id = await self._get_folder_id()
        client = self._get_client()
        resp = await client.get(
            f"{self.API}/folders/{folder_id}/items",
            params={"fields": "type,name", "limit": 1000},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        names = [
            e.get("name", "") for e in resp.json().get("entries", []) if e.get("type") == "file"
        ]
        return [n for n in names if n.startswith(prefix)]

    async def download(self, path: str) -> bytes:
        token = await self._ensure_valid_token()
        file_id = await self._file_id(path)
        client = self._get_client()
        resp = await client.get(
            f"{self.API}/files/{file_id}/content",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.content

    async def download_to_file(self, path: str, local_path: str) -> str:
        """Stream a Box download to *local_path* in chunks."""
        token = await self._ensure_valid_token()
        file_id = await self._file_id(path)
        client = self._get_client()
        with open(local_path, "wb") as fh:
            async with client.stream(
                "GET",
                f"{self.API}/files/{file_id}/content",
                headers={"Authorization": f"Bearer {token}"},
                timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    fh.write(chunk)
        return path

    async def delete(self, path: str) -> None:
        token = await self._ensure_valid_token()
        file_id = await self._file_id(path)
        client = self._get_client()
        resp = await client.delete(
            f"{self.API}/files/{file_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        resp.raise_for_status()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("Box provider HTTP client closed.")


# ── Pull-side merge helpers ────────────────────────────────────────────


# Operation precedence for tie-breaking when payloads carry no timestamp.
_SYNC_OP_PRECEDENCE = {"create": 1, "update": 2, "delete": 3}


def parse_sync_path(path: str) -> tuple[str, int, str] | None:
    """Parse ``lifelogr/{entity_type}/{entity_id}/{operation}.json``.

    Returns ``(entity_type, entity_id, operation)`` or ``None`` if *path* is not
    a sync op file (e.g. a ``lifelogr-backup-*.tar.gz`` archive or a directory).
    """
    parts = path.split("/")
    if len(parts) < 3:
        return None
    op_file = parts[-1]
    if not op_file.endswith(".json"):
        return None
    try:
        entity_id = int(parts[-2])
    except ValueError:
        return None
    operation = op_file[: -len(".json")]
    if operation not in _SYNC_OP_PRECEDENCE:
        return None
    return parts[-3], entity_id, operation


def _parse_dt_utc(raw: object) -> datetime | None:
    """Parse an ISO datetime to naive UTC, or ``None`` if unparseable/empty."""
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_date_field(raw: object) -> date | None:
    """Parse an ISO date (or the date prefix of a datetime) to ``date``."""
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


# ── High-level orchestration ───────────────────────────────────────────


class CloudSyncService:
    """High-level cloud sync orchestration with optional E2E encryption."""

    def __init__(self, db: AsyncSession, provider: SyncProvider) -> None:
        self.db = db
        self.provider = provider
        self._sync_svc = SyncService(db)

    async def __aenter__(self) -> CloudSyncService:
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        """Safely release connection resources from the provider."""
        if hasattr(self.provider, "close"):
            await self.provider.close()

    async def push(self, passphrase: str | None = None) -> dict[str, int]:
        """Push pending changes to cloud provider."""
        pending = await self._sync_svc.get_pending()
        pushed = 0
        for item in pending:
            data = item.payload.encode()
            path = f"lifelogr/{item.entity_type}/{item.entity_id}/{item.operation}.json"

            if passphrase:
                from app.services.encryption_service import EncryptionService

                key = EncryptionService._derive_key(passphrase)
                data = EncryptionService._encrypt(data, key).encode()

            await self.provider.upload(path, data, encrypted=bool(passphrase))
            pushed += 1

        if pushed:
            await self._sync_svc.flush()

        return {"pushed": pushed}

    async def pull(self, passphrase: str | None = None) -> dict[str, int]:
        """Pull and apply remote changes (last-writer-wins).

        Each remote file is ``lifelogr/{entity}/{id}/{op}.json`` whose body is
        the JSON payload queued at push time. Files are grouped by entity; the
        newest op per entity wins (by payload ``updated_at``, else op precedence
        delete>update>create). An op applies locally only when the remote write
        is newer than the local row, so re-pulling is idempotent.

        Entries and notes are fully merged. Anything else on the provider is
        legacy output from a client old enough to predate enqueue validation —
        it is counted as ``skipped`` (with a warning, never silently) and left
        in place. New clients cannot produce such files: enqueue rejects any
        entity type outside ``SYNCABLE_ENTITY_TYPES``.
        """
        from app.services.encryption_service import EncryptionService

        key = EncryptionService._derive_key(passphrase) if passphrase else None

        files = await self.provider.list_files("lifelogr/")
        # Newest op per entity: (operation, payload, updated_at, sort_key).
        winners: dict[
            tuple[str, int], tuple[str, dict[str, Any], datetime | None, tuple[datetime, int]]
        ] = {}
        for path in files:
            parsed = parse_sync_path(path)
            if parsed is None:
                continue
            entity_type, entity_id, operation = parsed
            try:
                content = await self.provider.download(path)
                if key is not None:
                    content = EncryptionService._decrypt(content.decode(), key)
                payload = json.loads(content)
            except Exception:
                logger.warning("sync: skipping unreadable remote op %s", path, exc_info=True)
                continue
            if not isinstance(payload, dict):
                continue
            ts = _parse_dt_utc(payload.get("updated_at"))
            sort_key = (ts or datetime.min, _SYNC_OP_PRECEDENCE[operation])
            current = winners.get((entity_type, entity_id))
            if current is None or sort_key > current[3]:
                winners[(entity_type, entity_id)] = (operation, payload, ts, sort_key)

        applied = 0
        skipped = 0
        for (entity_type, entity_id), (operation, payload, _ts, _key) in winners.items():
            apply_op = _ENTITY_APPLIERS.get(entity_type)
            if apply_op is None:
                # Legacy remote op for an entity type new clients cannot enqueue.
                skipped += 1
                logger.warning(
                    "sync: no merge support for entity type %r (entity %s); skipped",
                    entity_type,
                    entity_id,
                )
                continue
            try:
                if await apply_op(self, entity_id, operation, payload):
                    applied += 1
            except Exception:
                logger.exception(
                    "sync: failed applying %s %s %s", entity_type, entity_id, operation
                )

        if applied:
            status = await self._sync_svc._get_or_create_status("cloud")
            status.last_sync_at = datetime.now(timezone.utc)
            await self.db.commit()
        return {"pulled": applied, "skipped": skipped}

    async def _apply_entry_op(
        self, entity_id: int, operation: str, payload: dict[str, Any]
    ) -> bool:
        """Apply one entry op via last-writer-wins. True if it changed the row.

        Local ``updated_at`` is stored naive-UTC (SQLite ``CURRENT_TIMESTAMP``),
        so remote timestamps are normalised to naive-UTC for comparison.
        """
        from app.models.entry import Entry

        remote_updated = _parse_dt_utc(payload.get("updated_at"))
        existing = await self.db.get(Entry, entity_id)

        if operation == "delete":
            if existing is None:
                return False
            # No local row to compare, or remote delete is at least as new → honour it.
            if remote_updated is None or remote_updated >= existing.updated_at:
                existing.is_deleted = True
                existing.deleted_at = remote_updated
                if remote_updated:
                    existing.updated_at = remote_updated  # explicit set beats onupdate
                return True
            return False

        # create / update — skip if the local row is newer (LWW keeps local).
        if (
            existing is not None
            and remote_updated is not None
            and remote_updated < existing.updated_at
        ):
            return False

        entry_date = _parse_date_field(payload.get("entry_date"))
        if entry_date is None:
            logger.warning("sync: entry %s payload missing entry_date; skipping", entity_id)
            return False
        body = payload.get("body")
        fields: dict[str, Any] = {
            "entry_date": entry_date,
            "title": payload.get("title"),
            "body": "" if body is None else str(body),
            "mood": payload.get("mood"),
            "summary": payload.get("summary"),
            "is_deleted": bool(payload.get("is_deleted", False)),
        }
        target = existing if existing is not None else Entry(id=entity_id)
        for k, v in fields.items():
            setattr(target, k, v)
        if existing is None:
            created = _parse_dt_utc(payload.get("created_at"))
            if created:
                target.created_at = created
            self.db.add(target)
        if remote_updated:
            target.updated_at = remote_updated  # explicit set beats onupdate=func.now()
        return True

    async def _apply_note_op(self, entity_id: int, operation: str, payload: dict[str, Any]) -> bool:
        """Apply one note op via last-writer-wins. True if it changed the row.

        Mirrors :meth:`_apply_entry_op` (same LWW comparison, same explicit
        ``updated_at`` write to beat ``onupdate``), with note-specific handling:

        * ``folder_id`` — notes are hierarchical, so a payload can reference a
          folder this machine has not seen (folders are not themselves synced).
          SQLite enforces the FK, so a missing parent would fail the whole op;
          like entries ignore unknown tag ids, the note is applied *unfiled*
          (``folder_id = None``) with a warning rather than dropped.
        * Soft delete — same convention as the notes API: ``is_deleted`` +
          ``deleted_at``, never a hard delete.
        """
        from app.models.note import Note, NoteFolder

        remote_updated = _parse_dt_utc(payload.get("updated_at"))
        existing = await self.db.get(Note, entity_id)

        if operation == "delete":
            if existing is None:
                return False
            if remote_updated is None or remote_updated >= existing.updated_at:
                now = remote_updated or datetime.now(timezone.utc)
                existing.is_deleted = True
                existing.deleted_at = now
                existing.updated_at = now
                return True
            return False

        # create / update — skip if the local row is newer (LWW keeps local).
        if (
            existing is not None
            and remote_updated is not None
            and remote_updated < existing.updated_at
        ):
            return False

        body = payload.get("body")
        folder_id = payload.get("folder_id")
        if folder_id is not None:
            folder = await self.db.get(NoteFolder, int(folder_id))
            if folder is None:
                logger.warning(
                    "sync: note %s references missing folder %s; applying unfiled",
                    entity_id,
                    folder_id,
                )
                folder_id = None

        fields: dict[str, Any] = {
            "title": payload.get("title"),
            "body": "" if body is None else str(body),
            "is_pinned": bool(payload.get("is_pinned", False)),
            "color": payload.get("color"),
            "folder_id": int(folder_id) if folder_id is not None else None,
        }
        target = existing if existing is not None else Note(id=entity_id)
        for k, v in fields.items():
            setattr(target, k, v)
        # Encryption columns travel together or not at all: an is_encrypted flag
        # without its salt would make the body undecryptable on this machine.
        if payload.get("encryption_salt") is not None:
            target.encryption_salt = str(payload["encryption_salt"])
            target.is_encrypted = bool(payload.get("is_encrypted", True))
            target.encrypted_at = _parse_dt_utc(payload.get("encrypted_at"))
        if existing is None:
            created = _parse_dt_utc(payload.get("created_at"))
            if created:
                target.created_at = created
            self.db.add(target)
        if remote_updated:
            target.updated_at = remote_updated  # explicit set beats onupdate=func.now()
        return True


# Dispatch table for pull: every syncable entity type must have an applier here,
# and must be listed in SYNCABLE_ENTITY_TYPES so enqueue and pull stay in step.
_ENTITY_APPLIERS = {
    "entry": CloudSyncService._apply_entry_op,
    "note": CloudSyncService._apply_note_op,
}
