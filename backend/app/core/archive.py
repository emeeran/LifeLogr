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

import tarfile
from pathlib import Path


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


def add_backup_members(tar: tarfile.TarFile, db_file: str | Path, media_dir: str | Path) -> None:
    """Add the DB (+ WAL/SHM) and media dir to *tar* under standard arcnames.

    ``diarium.diarium`` (+ ``-wal``/``-shm``) is the on-disk name external tools
    expect; ``media/`` holds attachments. Missing files/dirs are skipped so the
    same helper works for a fresh install with no media yet.
    """
    db_path = Path(db_file)
    if db_path.exists():
        tar.add(str(db_path), arcname="diarium.diarium")
        # Belt-and-suspenders: bundle WAL/SHM so the archive is consistent even
        # if a pre-copy checkpoint couldn't fully finish, and opens correctly in
        # external tools that don't replay WAL.
        wal = db_path.with_suffix(db_path.suffix + "-wal")
        shm = db_path.with_suffix(db_path.suffix + "-shm")
        if wal.exists():
            tar.add(str(wal), arcname="diarium.diarium-wal")
        if shm.exists():
            tar.add(str(shm), arcname="diarium.diarium-shm")
    media_path = Path(media_dir)
    if media_path.exists():
        tar.add(str(media_path), arcname="media")
