"""Backup archive manifest: written by every producer, verified before restore."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from app.core.archive import MANIFEST_NAME, add_backup_members, verify_archive


def _build(tmp_path: Path, media: dict[str, bytes]) -> Path:
    db = tmp_path / "data" / "lifelogr.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"SQLite format 3\x00fake-db")
    media_dir = tmp_path / "media"
    for name, data in media.items():
        path = media_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    out = tmp_path / "backup.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        add_backup_members(tar, db, media_dir)
    return out


def test_manifest_lists_every_member(tmp_path: Path) -> None:
    out = _build(
        tmp_path,
        {"images/a.jpg": b"aaa", "audio/b.m4a": b"bbbb"},
    )
    with tarfile.open(out) as tar:
        manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())  # type: ignore[arg-type]

    assert manifest["database"] == "diarium.diarium"
    assert {entry["name"] for entry in manifest["files"]} == {
        "diarium.diarium",
        "media/images/a.jpg",
        "media/audio/b.m4a",
    }
    assert manifest["counts"]["files"] == 3
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])


def test_verify_accepts_a_fresh_archive(tmp_path: Path) -> None:
    report = verify_archive(_build(tmp_path, {"images/a.jpg": b"aaa"}))
    assert report["valid"] is True
    assert report["legacy"] is False
    assert report["files"] == 2
    assert report["errors"] == []
    assert report["database"] == "diarium.diarium"


def test_verify_detects_a_changed_member(tmp_path: Path) -> None:
    original = _build(tmp_path, {"images/a.jpg": b"aaa"})
    with tarfile.open(original) as tar:
        manifest = tar.extractfile(MANIFEST_NAME).read()  # type: ignore[union-attr]
        members = {
            member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
            for member in tar.getmembers()
            if member.isfile() and member.name != MANIFEST_NAME
        }

    members["media/images/a.jpg"] = b"tampered"
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))

    report = verify_archive(tampered)
    assert report["valid"] is False
    assert any("media/images/a.jpg" in error for error in report["errors"])


def test_verify_flags_a_missing_member(tmp_path: Path) -> None:
    original = _build(tmp_path, {"images/a.jpg": b"aaa", "images/b.jpg": b"bbb"})
    with tarfile.open(original) as tar:
        manifest = tar.extractfile(MANIFEST_NAME).read()  # type: ignore[union-attr]
        members = {
            member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
            for member in tar.getmembers()
            if member.isfile()
            and member.name != MANIFEST_NAME
            and member.name != "media/images/b.jpg"
        }

    partial = tmp_path / "partial.tar.gz"
    with tarfile.open(partial, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))

    report = verify_archive(partial)
    assert report["valid"] is False
    assert report["missing"] == ["media/images/b.jpg"]


def test_legacy_archive_without_a_manifest_is_accepted(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.tar.gz"
    db = tmp_path / "dev.db"
    db.write_bytes(b"SQLite format 3\x00old")
    with tarfile.open(legacy, "w:gz") as tar:
        tar.add(str(db), arcname="dev.db")

    report = verify_archive(legacy)
    assert report["valid"] is True
    assert report["legacy"] is True
    assert report["errors"] == []


def test_unreadable_archive_is_reported_not_raised(tmp_path: Path) -> None:
    broken = tmp_path / "broken.tar.gz"
    broken.write_bytes(b"not a tarball")
    report = verify_archive(broken)
    assert report["valid"] is False
    assert report["errors"] and "unreadable archive" in report["errors"][0]
