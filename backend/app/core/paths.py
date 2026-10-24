"""Filesystem path-safety helpers for user-supplied backup locations.

The backup endpoints are unauthenticated (Tauri loopback), so a client value
— or a malicious local script / cross-site request that can reach the port —
must never be turned into an arbitrary filesystem write. ``resolve_backup_path``
confines backup writes to an allowlist of roots; anything outside it (system
directories, other users' space) is rejected.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def allowed_backup_roots() -> list[Path]:
    """Roots a user-supplied backup directory may live under.

    Covers the realistic local-backup destinations without letting an
    unauthenticated request reach sensitive filesystem areas:

    * the user's home — ``~/Backups``, ``~/Documents``, …
    * the app data directory
    * the system temp directory — ad-hoc / test destinations; writing a
      ``lifelogr-backup-*.tar.gz`` there is low-harm
    * any extra root the operator configures via ``BACKUP_ALLOWED_ROOTS``
      (comma-separated) — e.g. an external drive or NAS: ``/media,/mnt``

    Everything else — ``/etc``, ``/usr``, ``/root``, another user's home —
    falls outside this set and is rejected.
    """
    from app.core.config import settings

    roots: list[Path] = []
    home = Path.home()
    if str(home) not in ("/", ""):
        roots.append(home.resolve())
    data_dir = Path(settings.DATA_DIR).resolve()
    if data_dir not in roots:
        roots.append(data_dir)
    tmp = Path(tempfile.gettempdir()).resolve()
    if tmp not in roots:
        roots.append(tmp)
    extra = getattr(settings, "BACKUP_ALLOWED_ROOTS", "") or ""
    for raw in str(extra).split(","):
        raw = raw.strip()
        if raw:
            root = Path(raw).expanduser().resolve()
            if root not in roots:
                roots.append(root)
    return roots


def resolve_backup_path(path: str | Path | None) -> Path:
    """Validate and resolve a user-supplied backup directory.

    Returns the resolved Path. Raises ``ValueError`` if the path escapes every
    allowed root (system directories and other users' space are off-limits).
    Symlinks are followed via ``resolve()`` *before* the containment check, so a
    symlink that points outside an allowed root is rejected rather than used to
    smuggle a write past the guard.
    """
    if path is None or str(path) == "":
        raise ValueError("Backup path is required")
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:  # pragma: no cover - pathological fs
        raise ValueError(f"Invalid backup path: {path!r}") from exc

    for root in allowed_backup_roots():
        # is_relative_to returns False (never raises) for two absolute paths.
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise ValueError(
        "Backup directory must be inside your home folder, the app data "
        f"directory, or the system temp dir (got {path!r})."
    )
