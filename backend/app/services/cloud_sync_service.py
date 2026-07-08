"""Cloud sync service — E2E encrypted sync with provider adapters."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol, cast

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

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        target = self._base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    async def download(self, path: str) -> bytes:
        target = self._base / path
        return target.read_bytes()

    async def list_files(self, prefix: str) -> list[str]:
        if not self._base.exists():
            return []
        return [
            str(p.relative_to(self._base)) for p in self._base.rglob(f"{prefix}*") if p.is_file()
        ]

    async def delete(self, path: str) -> None:
        target = self._base / path
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
    """Google Drive sync provider with a shared httpx client."""

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

    async def _find_file_id(self, path: str) -> str | None:
        """Find the unique Google Drive file ID matching the file path/name."""
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        headers = {"Authorization": f"Bearer {token}"}

        query = f"name = '{path}' and 'appDataFolder' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}&spaces=appDataFolder"

        client = self._get_client()
        resp = await client.get(url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        return files[0]["id"] if files else None

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        import json as _json

        token = await self._ensure_valid_token()
        file_id = await self._find_file_id(path)
        client = self._get_client()

        if file_id:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            }
            resp = await client.patch(url, headers=headers, content=data, timeout=15.0)
            resp.raise_for_status()
            return path
        else:
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            boundary = b"lifelogr_upload_boundary"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary.decode()}",
            }

            metadata = {"name": path, "parents": ["appDataFolder"]}

            body = (
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                + _json.dumps(metadata).encode("utf-8")
                + b"\r\n"
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n"
                b"--" + boundary + b"--\r\n"
            )

            resp = await client.post(url, headers=headers, content=body, timeout=15.0)
            resp.raise_for_status()
            return path

    async def download(self, path: str) -> bytes:
        token = await self._ensure_valid_token()
        file_id = await self._find_file_id(path)
        if not file_id:
            raise FileNotFoundError(f"File not found on Google Drive: {path}")

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {token}"}

        client = self._get_client()
        resp = await client.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp.content

    async def list_files(self, prefix: str) -> list[str]:
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        headers = {"Authorization": f"Bearer {token}"}

        query = f"name contains '{prefix}' and 'appDataFolder' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}&spaces=appDataFolder"

        client = self._get_client()
        resp = await client.get(url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        return [f["name"] for f in files]

    async def delete(self, path: str) -> None:
        token = await self._ensure_valid_token()
        file_id = await self._find_file_id(path)
        if not file_id:
            return

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        headers = {"Authorization": f"Bearer {token}"}

        client = self._get_client()
        resp = await client.delete(url, headers=headers, timeout=10.0)
        resp.raise_for_status()

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
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=data,
            timeout=30.0,
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
            e.get("name", "")
            for e in resp.json().get("entries", [])
            if e.get("type") == "file"
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


# ── MEGA provider ──────────────────────────────────────────────────────


class MegaClient(Protocol):
    def create_folder(self, name: str, dest: str) -> object: ...
    def upload(self, filename: str, dest: str, dest_filename: str) -> object: ...
    def find(self, path: str) -> object: ...
    def download(self, file_info: object, dest_path: str) -> object: ...
    def get_files(self) -> dict[str, object]: ...
    def delete(self, file_info: object) -> object: ...


class MegaProvider:
    """MEGA cloud sync provider using mega.py library."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._mega: MegaClient | None = None

    def _get_sync_client(self) -> MegaClient:
        """Get or create the synchronous MEGA client."""
        if self._mega is None:
            try:
                from mega import Mega  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError(
                    "MEGA cloud sync requires the 'cloud' extra. "
                    'Install it with: uv pip install -e ".[cloud]"'
                ) from exc

            m = Mega()
            self._mega = cast(MegaClient, m.login(self._email, self._password))
        return self._mega

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        import tempfile
        from pathlib import Path

        mega = await asyncio.to_thread(self._get_sync_client)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            parts = path.split("/")
            folder = "/"
            for part in parts[:-1]:
                if part:
                    try:
                        await asyncio.to_thread(mega.create_folder, part, folder)
                    except Exception:
                        logger.debug("Folder creation skipped (likely exists): %s", part)
                    folder = folder.rstrip("/") + "/" + part

            await asyncio.to_thread(mega.upload, tmp_path, folder, parts[-1])
            return path
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def download(self, path: str) -> bytes:
        import tempfile
        from pathlib import Path

        mega = await asyncio.to_thread(self._get_sync_client)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp_path = tmp.name

        try:
            file_info = await asyncio.to_thread(mega.find, path)
            if not file_info:
                raise FileNotFoundError(f"File not found on MEGA: {path}")
            await asyncio.to_thread(mega.download, file_info, tmp_path)
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def list_files(self, prefix: str) -> list[str]:
        mega = await asyncio.to_thread(self._get_sync_client)
        try:
            files = await asyncio.to_thread(mega.get_files)
            found: list[str] = []
            needle = prefix.split("/")[-1] if "/" in prefix else prefix
            for item in files.values():
                if not isinstance(item, dict):
                    continue
                attrs = item.get("a")
                if not isinstance(attrs, dict):
                    continue
                name = attrs.get("n")
                if isinstance(name, str) and name.startswith(needle):
                    found.append(name)
            return found
        except Exception:
            logger.warning("Failed to list MEGA files", exc_info=True)
            return []

    async def delete(self, path: str) -> None:
        mega = await asyncio.to_thread(self._get_sync_client)
        try:
            file_info = await asyncio.to_thread(mega.find, path)
            if file_info:
                await asyncio.to_thread(
                    mega.delete, file_info[0] if isinstance(file_info, list) else file_info
                )
        except Exception:
            logger.warning("Failed to delete MEGA file: %s", path, exc_info=True)

    async def close(self) -> None:
        """MEGA provider uses short-lived sync calls and holds no async handles."""
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

    async def __aexit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
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
        """Pull changes from cloud provider."""
        files = await self.provider.list_files("lifelogr/")
        pulled = 0
        for path in files:
            data = await self.provider.download(path)
            if passphrase:
                from app.services.encryption_service import EncryptionService

                key = EncryptionService._derive_key(passphrase)
                data = EncryptionService._decrypt(data.decode(), key)
            pulled += 1

        return {"pulled": pulled}
