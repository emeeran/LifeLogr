"""Cloud sync service — E2E encrypted sync with provider adapters."""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sync_service import SyncService


class SyncProvider(Protocol):
    """Interface for cloud sync providers."""
    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str: ...
    async def download(self, path: str) -> bytes: ...
    async def list_files(self, prefix: str) -> list[str]: ...
    async def delete(self, path: str) -> None: ...


class LocalFileProvider:
    """Local filesystem sync provider (for testing/dev)."""

    def __init__(self, base_dir: str = "/tmp/diarilinux-sync") -> None:
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
            str(p.relative_to(self._base))
            for p in self._base.rglob(f"{prefix}*")
            if p.is_file()
        ]

    async def delete(self, path: str) -> None:
        target = self._base / path
        if target.exists():
            target.unlink()


class NextcloudProvider:
    """Nextcloud WebDAV sync provider."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._url = base_url.rstrip("/")
        self._auth = (username, password)

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
                content=data,
                auth=self._auth,
            )
            resp.raise_for_status()
            return path

    async def download(self, path: str) -> bytes:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
                auth=self._auth,
            )
            resp.raise_for_status()
            return resp.content

    async def list_files(self, prefix: str) -> list[str]:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                "PROPFIND",
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/",
                auth=self._auth,
                headers={"Depth": "1"},
            )
            # Parse basic file list from XML
            files = []
            if resp.status_code == 207:
                for line in resp.text.splitlines():
                    if prefix in line:
                        files.append(line.strip())
            return files

    async def delete(self, path: str) -> None:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._url}/remote.php/dav/files/{self._auth[0]}/{path}",
                auth=self._auth,
            )
            resp.raise_for_status()


class GoogleDriveProvider:
    """Google Drive async sync provider implementing the SyncProvider protocol."""

    def __init__(
        self,
        credentials: dict[str, str],
        on_token_refresh: callable | None = None
    ) -> None:
        self._client_id = credentials.get("client_id") or "diarilinux-client-id.apps.googleusercontent.com"
        self._client_secret = credentials.get("client_secret") or "GOCSPX-diarilinux-secret"
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")  # timestamp as str/float
        self._on_token_refresh = on_token_refresh

    async def _ensure_valid_token(self) -> str:
        """Refreshes the access token if expired or missing."""
        import time
        import httpx

        now = time.time()
        # If we have an access token and it's not expired (buffer of 60 seconds)
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token

        if not self._refresh_token:
            raise ValueError("Refresh token missing from Google Drive credentials")

        # Perform token refresh
        async with httpx.AsyncClient() as client:
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
        import httpx
        from urllib.parse import quote

        token = await self._ensure_valid_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        # Escape path for query safely
        query = f"name = '{path}' and 'appDataFolder' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}&spaces=appDataFolder"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            files = resp.json().get("files", [])
            return files[0]["id"] if files else None

    async def upload(self, path: str, data: bytes, encrypted: bool = True) -> str:
        import json
        import httpx
        token = await self._ensure_valid_token()
        
        file_id = await self._find_file_id(path)
        
        if file_id:
            # Update existing file content
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.patch(url, headers=headers, content=data, timeout=15.0)
                resp.raise_for_status()
                return path
        else:
            # Create new file using multipart upload
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            boundary = b"diarilinux_upload_boundary"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary.decode()}",
            }
            
            metadata = {
                "name": path,
                "parents": ["appDataFolder"]
            }
            
            body = (
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                + json.dumps(metadata).encode("utf-8") + b"\r\n"
                b"--" + boundary + b"\r\n"
                b"Content-Type: application/octet-stream\r\n\r\n"
                + data + b"\r\n"
                b"--" + boundary + b"--\r\n"
            )
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, content=body, timeout=15.0)
                resp.raise_for_status()
                return path

    async def download(self, path: str) -> bytes:
        import httpx
        token = await self._ensure_valid_token()
        file_id = await self._find_file_id(path)
        if not file_id:
            raise FileNotFoundError(f"File not found on Google Drive: {path}")

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=15.0)
            resp.raise_for_status()
            return resp.content

    async def list_files(self, prefix: str) -> list[str]:
        import httpx
        from urllib.parse import quote
        
        token = await self._ensure_valid_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        query = f"name contains '{prefix}' and 'appDataFolder' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={quote(query)}&spaces=appDataFolder"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            files = resp.json().get("files", [])
            return [f["name"] for f in files]

    async def delete(self, path: str) -> None:
        import httpx
        token = await self._ensure_valid_token()
        file_id = await self._find_file_id(path)
        if not file_id:
            return

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=10.0)
            resp.raise_for_status()


class CloudSyncService:
    """High-level cloud sync orchestration with optional E2E encryption."""

    def __init__(self, db: AsyncSession, provider: SyncProvider) -> None:
        self.db = db
        self.provider = provider
        self._sync_svc = SyncService(db)

    async def push(self, passphrase: str | None = None) -> dict[str, int]:
        """Push pending changes to cloud provider."""
        pending = await self._sync_svc.get_pending()
        pushed = 0
        for item in pending:
            data = item.payload.encode()
            path = f"diarilinux/{item.entity_type}/{item.entity_id}/{item.operation}.json"

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
        files = await self.provider.list_files("diarilinux/")
        pulled = 0
        for path in files:
            data = await self.provider.download(path)
            if passphrase:
                from app.services.encryption_service import EncryptionService
                key = EncryptionService._derive_key(passphrase)
                data = EncryptionService._decrypt(data.decode(), key)
            pulled += 1

        return {"pulled": pulled}
