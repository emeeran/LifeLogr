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
