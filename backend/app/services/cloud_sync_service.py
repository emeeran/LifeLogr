"""Cloud sync service — E2E encrypted sync with provider adapters."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import SyncQueue, SyncStatus

logger = logging.getLogger(__name__)


# ── Sync queue helpers (inlined from sync_service.py) ──────────────────


class SyncService:
    """Offline queue, flush, and conflict resolution."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue(
        self, operation: str, entity_type: str, entity_id: int, payload: dict[str, object]
    ) -> SyncQueue:
        """Queue an operation for later sync."""
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

    async def upload_file(
        self, path: str, local_path: str, encrypted: bool = False
    ) -> str: ...
    async def download(self, path: str) -> bytes: ...
    async def list_files(self, prefix: str) -> list[str]: ...
    async def delete(self, path: str) -> None: ...
    async def close(self) -> None: ...


# ── Local filesystem provider ──────────────────────────────────────────


class LocalFileProvider:
    """Local filesystem sync provider (for testing/dev)."""

    def __init__(self, base_dir: str = "/tmp/lifelogr-sync") -> None:
        from pathlib import Path

        self._base = Path(base_dir)

    def _safe_target(self, path: str):
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
        """Stream a local file to WebDAV (httpx streams the open file handle)."""
        client = self._get_client()
        with open(local_path, "rb") as fh:
            resp = await client.put(
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
                content=fh,
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

    async def list_files(self, prefix: str) -> list[str]:
        client = self._get_client()
        resp = await client.request(
            "PROPFIND",
            f"{self._url}/remote.php/dav/files/{self._auth[0]}/",
            auth=self._auth,
            headers={"Depth": "1"},
        )
        files = []
        if resp.status_code == 207:
            for line in resp.text.splitlines():
                if prefix in line:
                    files.append(line.strip())
        return files

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


class GoogleDriveProvider:
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

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

    async def _query_files(self, query: str, *, spaces: str = "") -> list[dict]:
        """Run a Drive files.list query and return the raw file dicts."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}"
        if spaces:
            url += f"&spaces={spaces}"
        client = self._get_client()
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        resp.raise_for_status()
        return resp.json().get("files", [])

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

        Existing files are updated with a streaming media PATCH. The first-ever
        backup for a name has no streaming create path wired, so it falls back
        to the bytes-based ``_create_in_folder``; subsequent runs stream.
        """
        from pathlib import Path

        token = await self._ensure_valid_token()
        parent = await self._get_folder_or_appdata()
        look_in = "appdata" if parent == "appDataFolder" else "folder"
        file_id = await self._find_file_id(path, look_in=look_in)
        client = self._get_client()
        if file_id:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            with open(local_path, "rb") as fh:
                resp = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/octet-stream",
                    },
                    content=fh,
                    timeout=300.0,
                )
            resp.raise_for_status()
            self.last_location = look_in
            return path
        await self._create_in_folder(path, Path(local_path).read_bytes(), parent)
        self.last_location = look_in
        return path

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

    async def download(self, path: str) -> bytes:
        # Visible folder first, then legacy App Data for unmigrated backups.
        file_id = await self._find_file_id(path, look_in="folder")
        if not file_id:
            file_id = await self._find_file_id(path, look_in="appdata")
        if not file_id:
            raise FileNotFoundError(f"File not found on Google Drive: {path}")
        return await self._download_by_id(file_id)

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


class OneDriveProvider:
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

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
        """Stream a local file to OneDrive (httpx streams the open file handle)."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        client = self._get_client()
        with open(local_path, "rb") as fh:
            resp = await client.put(
                f"{self.GRAPH}:{quote(path)}:/content",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                },
                content=fh,
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


class DropboxProvider:
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

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
        """Stream a local file to Dropbox (httpx streams the open file handle)."""
        token = await self._ensure_valid_token()
        client = self._get_client()
        with open(local_path, "rb") as fh:
            resp = await client.post(
                f"{self.CONTENT}/files/upload",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Dropbox-API-Arg": self._api_arg(path, mode="overwrite"),
                    "Content-Type": "application/octet-stream",
                },
                content=fh,
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


class BoxProvider:
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

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
        for entry in resp.json().get("entries", []):
            if entry.get("type") == "file" and entry.get("name") == name:
                return entry["id"]
        raise ValueError(f"File '{name}' not found in Box folder")

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        token = await self._ensure_valid_token()
        folder_id = await self._get_folder_id()
        client = self._get_client()
        # Box file upload is multipart: an `attributes` JSON field + the file.
        files = {
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
        files = {
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

        Entries are fully merged. Media/tag are parsed but skipped for now (they
        need blob / model wiring beyond this change) and counted as ``skipped``.
        """
        from app.services.encryption_service import EncryptionService

        key = EncryptionService._derive_key(passphrase) if passphrase else None

        files = await self.provider.list_files("lifelogr/")
        # Newest op per entity: (operation, payload, updated_at, sort_key).
        winners: dict[tuple[str, int], tuple[str, dict[str, Any], datetime | None, tuple]] = {}
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
            if entity_type == "entry":
                try:
                    if await self._apply_entry_op(entity_id, operation, payload):
                        applied += 1
                except Exception:
                    logger.exception("sync: failed applying entry %s %s", entity_id, operation)
            else:
                # Media/tag merge is a follow-up (blob handling / model wiring).
                skipped += 1
                logger.info("sync: %s merge not implemented; skipped entity %s", entity_type, entity_id)

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
