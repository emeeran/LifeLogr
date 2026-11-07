"""`POST /backup/verify` reports integrity; restore refuses a bad archive."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from httpx import AsyncClient

from app.core.archive import MANIFEST_NAME, add_backup_members


def _archive(tmp_path: Path, *, tamper: bool) -> bytes:
    db = tmp_path / "data" / "lifelogr.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"SQLite format 3\x00fake")
    media = tmp_path / "media"
    (media / "images").mkdir(parents=True, exist_ok=True)
    (media / "images" / "a.jpg").write_bytes(b"photo-bytes")

    original = tmp_path / "backup.tar.gz"
    with tarfile.open(original, "w:gz") as tar:
        add_backup_members(tar, db, media)

    if not tamper:
        return original.read_bytes()

    with tarfile.open(original) as tar:
        manifest = tar.extractfile(MANIFEST_NAME).read()  # type: ignore[union-attr]
        members = {
            member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
            for member in tar.getmembers()
            if member.isfile() and member.name != MANIFEST_NAME
        }
    members["media/images/a.jpg"] = b"bit-rot"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return buf.getvalue()


async def test_verify_reports_a_healthy_archive(
    client: AsyncClient, tmp_path: Path
) -> None:
    r = await client.post(
        "/api/v1/backup/verify",
        files={"file": ("backup.tar.gz", _archive(tmp_path, tamper=False))},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["legacy"] is False
    assert body["files"] == 2
    assert body["database"] == "diarium.diarium"


async def test_verify_names_the_damaged_member(
    client: AsyncClient, tmp_path: Path
) -> None:
    r = await client.post(
        "/api/v1/backup/verify",
        files={"file": ("backup.tar.gz", _archive(tmp_path, tamper=True))},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any("media/images/a.jpg" in error for error in body["errors"])


async def test_import_refuses_an_archive_that_fails_verification(
    client: AsyncClient, tmp_path: Path
) -> None:
    r = await client.post(
        "/api/v1/backup/import",
        files={"file": ("backup.tar.gz", _archive(tmp_path, tamper=True))},
    )
    assert r.status_code == 400
    assert "verification" in r.json()["detail"].lower()
