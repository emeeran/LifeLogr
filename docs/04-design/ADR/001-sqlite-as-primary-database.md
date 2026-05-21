# ADR-001: SQLite as Primary Database

## Status: Accepted

## Context

DiariumLinux is a single-user, offline-first journaling app running on Linux desktop. The database must support CRUD operations for entries, tags, media metadata, and backup state. Expected load is a single user with no concurrent writes beyond background backup tasks.

Options evaluated:
- **SQLite** — embedded, file-based, zero-config
- **PostgreSQL** — full RDBMS, requires separate server process
- **PostgreSQL (prod) / SQLite (dev)** — dual-database strategy

## Decision

Use SQLite exclusively for both development and production.

## Consequences

- **No separate database process** — the app starts instantly and needs no system service management.
- **Single-file portability** — the entire database is one file the user can copy, back up, or move (NFR-007).
- **Offline-first guaranteed** — SQLite has no network dependency; the app works with zero connectivity (NFR-001).
- **Performance** — SQLite handles single-user read/write workloads with sub-millisecond latency on local SSD, well under the 200 ms NFR-002 target.
- **Concurrency** — SQLite supports one writer at a time. For this single-user app, concurrent writes from the backup background task are the only overlap — handled via WAL mode and short transactions.
- **Limitations** — No built-in full-text search (FTS5 extension must be enabled). No native JSON queries. These are acceptable trade-offs.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| PostgreSQL | Requires system service, user setup, and network; violates offline-first and portability goals |
| Dual-database (SQLite dev / PostgreSQL prod) | Adds complexity for a single-user app; no benefit since SQLite meets all NFRs |
