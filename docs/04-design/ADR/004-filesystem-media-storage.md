# ADR-004: Local Filesystem for Media Storage

## Status: Accepted

## Context

Media attachments (images, videos, documents, audio) need persistent storage. The app must store files up to 25 MB each and retrieve them for inline display in entries. Options:

- **Local filesystem** — files stored in a configurable directory, path referenced in DB
- **Database BLOB** — files stored as binary data in the `media` table
- **Object storage (S3-compatible)** — files stored in cloud object storage

## Decision

Store media files on the local filesystem under a configurable `MEDIA_DIR`, organized by type (`images/`, `videos/`, `audio/`, `documents/`). Files are named by UUID to avoid collisions. The `media.storage_path` column stores the relative path.

## Consequences

- **Offline-first** — no network dependency for media access (NFR-001).
- **Performance** — filesystem reads are faster than BLOB extraction from SQLite for large files.
- **Portability** — the media directory can be copied alongside the SQLite database for backup or migration.
- **Backup integration** — the `BackupService` uploads files from `MEDIA_DIR` alongside the database delta.
- **Disk usage** — media files are outside the database, keeping the SQLite file small and fast to back up.
- **Orphan risk** — if an entry is deleted, media files must be cleaned up. The `MediaService.delete_by_entry` method handles this cascade.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| Database BLOB | Bloats SQLite file; poor performance for large files; complicates backup (entire DB becomes huge) |
| Object storage (S3) | Requires network, violates offline-first; adds infrastructure complexity for a single-user desktop app |
