"""Shared tar archive helpers: safe extraction + standard backup assembly.

Two concerns live here:

* ``extract_tar_safely`` / ``extract_archive_file`` — defence-in-depth
  extraction used by *every* restore path (manual import, cloud restore), from
  either an open archive or a file on disk. Centralising the path-traversal
  guard keeps it from drifting between call sites.
* ``add_backup_members`` — the DB (+ WAL/SHM sidecars) and ``media/`` layout
  written identically by local export, scheduled local backup, and cloud
  backup. Building them in one place keeps the three producers byte-for-byte
  consistent and lets each choose its own *target* (file vs. in-memory) without
  re-implementing the layout.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from app.core.jobs import ProgressReporter

# Bumped whenever the manifest schema changes. Archives without a manifest are
# accepted as legacy (verification is skipped, with a warning).
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 2

# Optional progress callback: (phase, done, total). Phases: "database" then
# "media". Total counts DB members + media files; None total = unknown.
# Same shape as core.jobs.ProgressReporter; aliased so call sites can pass a
# job reporter or a bare closure interchangeably.
ArchiveProgressFn = ProgressReporter


def _assert_member_name_safe(name: str) -> None:
    """Reject absolute paths and any ``..`` path *segment*.

    A substring check (``".." in name``) wrongly rejects legitimate names like
    ``foo..bar``; checking ``Path(name).parts`` only flags an actual parent
    component. This is belt-and-suspenders on top of PEP 706 ``filter="data"``,
    which separately strips symlinks/hardlinks/device files.
    """
    if name.startswith(("/", "\\")):
        raise ValueError(f"Unsafe archive entry (absolute path): {name!r}")
    if ".." in Path(name).parts:
        raise ValueError(f"Unsafe archive entry (path traversal): {name!r}")


def extract_tar_safely(tar: tarfile.TarFile, dest: str | Path) -> None:
    """Extract *tar* into *dest* with traversal + symlink guards.

    Raises ``ValueError`` on any unsafe member or tar error; never extracts
    symlinks, hardlinks, or device files (``filter="data"``).
    """
    dest_path = Path(dest)
    for member in tar.getmembers():
        _assert_member_name_safe(member.name)
    try:
        tar.extractall(dest_path, filter="data")
    except tarfile.TarError as exc:
        raise ValueError(f"Invalid archive: {exc}") from exc


def extract_archive_file(archive_path: str | Path, dest: str | Path) -> None:
    """Extract the ``.tar.gz`` at *archive_path* into *dest* (guarded).

    Reads straight from disk, so a restore never has to hold the archive in
    memory. Synchronous and potentially slow — run it in a thread. Raises
    ``ValueError`` for an unreadable or unsafe archive (callers map that to a
    400); the traversal/symlink guards are the shared ``extract_tar_safely``.
    """
    try:
        with tarfile.open(archive_path, mode="r:gz") as tar:
            extract_tar_safely(tar, dest)
    except tarfile.TarError as exc:
        raise ValueError(f"Invalid archive: {exc}") from exc


class _HashingReader:
    """File wrapper that hashes bytes as tarfile consumes them.

    Hashing during the single read ``add_backup_members`` already performs keeps
    a multi-GB backup from needing a second pass over every media file.
    """

    def __init__(self, fh: IO[bytes], digest: Any) -> None:
        self._fh = fh
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        if data:
            self._digest.update(data)
        return data


def _add_hashed(
    tar: tarfile.TarFile,
    src: Path,
    arcname: str,
    files: list[dict[str, Any]],
) -> None:
    """Add one regular file to *tar* and record its size + sha256."""
    info = tar.gettarinfo(str(src), arcname=arcname)
    digest = hashlib.sha256()
    with src.open("rb") as fh:
        tar.addfile(info, _HashingReader(fh, digest))
    files.append({"name": arcname, "size": info.size, "sha256": digest.hexdigest()})


def _add_manifest(
    tar: tarfile.TarFile,
    files: list[dict[str, Any]],
    database: str | None,
) -> None:
    """Append ``manifest.json`` last, so it lists every member before it."""
    from app.core.config import settings

    payload = {
        "format": MANIFEST_FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": settings.APP_VERSION,
        "database": database,
        "files": files,
        "counts": {
            "files": len(files),
            "bytes": sum(int(entry["size"]) for entry in files),
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    info = tarfile.TarInfo(MANIFEST_NAME)
    info.size = len(raw)
    info.mtime = int(time.time())
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(raw))


def add_backup_members(
    tar: tarfile.TarFile,
    db_file: str | Path,
    media_dir: str | Path,
    report: ArchiveProgressFn | None = None,
) -> None:
    """Add the DB (+ WAL/SHM), media dir and integrity manifest to *tar*.

    ``diarium.diarium`` (+ ``-wal``/``-shm``) is the on-disk name external tools
    expect; ``media/`` holds attachments. Missing files/dirs are skipped so the
    same helper works for a fresh install with no media yet.

    Every member is hashed as it is written and recorded in ``manifest.json``
    (last member). ``verify_archive`` checks those digests before a restore, so
    a truncated download or bit-rot fails loudly instead of replacing good data.

    *report* (optional) receives (phase, done, total) as members are written.
    """
    done = 0
    files: list[dict[str, Any]] = []
    database: str | None = None
    db_members: list[tuple[str, str]] = []
    db_path = Path(db_file)
    if db_path.exists():
        db_members.append((str(db_path), "diarium.diarium"))
        database = "diarium.diarium"
        # Belt-and-suspenders: bundle WAL/SHM so the archive is consistent even
        # if a pre-copy checkpoint couldn't fully finish, and opens correctly in
        # external tools that don't replay WAL.
        wal = db_path.with_suffix(db_path.suffix + "-wal")
        shm = db_path.with_suffix(db_path.suffix + "-shm")
        if wal.exists():
            db_members.append((str(wal), "diarium.diarium-wal"))
        if shm.exists():
            db_members.append((str(shm), "diarium.diarium-shm"))

    media_path = Path(media_dir)
    media_files: list[Path] = []
    if media_path.exists():
        media_files = sorted(p for p in media_path.rglob("*") if p.is_file())

    total = len(db_members) + len(media_files)
    if total == 0:
        # Fresh install: keep the single zero-progress event callers expect,
        # while still emitting a (empty) manifest.
        if report is not None:
            report("archive", 0, 0)
        _add_manifest(tar, files, database)
        return
    if report is not None:
        report("database", 0, total)

    for src, arcname in db_members:
        _add_hashed(tar, Path(src), arcname, files)
        done += 1
        if report is not None:
            report("database", done, total)

    if report is not None:
        report("media", done, total)
    for path in media_files:
        _add_hashed(tar, path, f"media/{path.relative_to(media_path)}", files)
        done += 1
        if report is not None:
            report("media", done, total)

    # Preserve an empty media directory (a restore checks for `media/`).
    if media_path.exists() and not media_files:
        info = tarfile.TarInfo("media/")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.mtime = int(time.time())
        tar.addfile(info)

    _add_manifest(tar, files, database)


def verify_archive(archive_path: str | Path) -> dict[str, Any]:
    """Check an archive against its embedded manifest.

    Returns a report rather than raising: "valid" answers integrity, while
    "legacy" marks archives built before manifests existed (nothing to check).
    Members are hashed straight from the tar stream, so this never extracts to
    disk and is safe to run on an upload before a restore.
    """
    errors: list[str] = []
    missing: list[str] = []
    try:
        with tarfile.open(archive_path, mode="r:gz") as tar:
            names = set(tar.getnames())
            if MANIFEST_NAME not in names:
                return {
                    "valid": True,
                    "legacy": True,
                    "format": None,
                    "created_at": None,
                    "app_version": None,
                    "database": None,
                    "files": len(names),
                    "bytes": 0,
                    "errors": [],
                    "missing": [],
                }

            manifest_file = tar.extractfile(MANIFEST_NAME)
            if manifest_file is None:
                raise ValueError("manifest is not a regular file")
            manifest = json.loads(manifest_file.read().decode("utf-8"))
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise ValueError("manifest has no files list")

            total_bytes = 0
            for entry in entries:
                name = entry.get("name") if isinstance(entry, dict) else None
                if not isinstance(name, str):
                    errors.append("manifest entry without a name")
                    continue
                try:
                    member = tar.extractfile(name)
                except KeyError:
                    member = None
                if member is None:
                    missing.append(name)
                    errors.append(f"missing: {name}")
                    continue
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = member.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                total_bytes += size
                expected_size = entry.get("size")
                expected_hash = entry.get("sha256")
                if isinstance(expected_size, int) and size != expected_size:
                    errors.append(f"size mismatch: {name} ({size} != {expected_size})")
                elif (
                    isinstance(expected_hash, str)
                    and digest.hexdigest() != expected_hash
                ):
                    errors.append(f"checksum mismatch: {name}")

            return {
                "valid": not errors,
                "legacy": False,
                "format": manifest.get("format"),
                "created_at": manifest.get("created_at"),
                "app_version": manifest.get("app_version"),
                "database": manifest.get("database"),
                "files": len(entries),
                "bytes": total_bytes,
                "errors": errors,
                "missing": missing,
            }
    except (tarfile.TarError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "legacy": False,
            "format": None,
            "created_at": None,
            "app_version": None,
            "database": None,
            "files": 0,
            "bytes": 0,
            "errors": [f"unreadable archive: {exc}"],
            "missing": [],
        }


