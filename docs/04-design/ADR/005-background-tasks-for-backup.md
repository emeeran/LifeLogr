# ADR-005: FastAPI BackgroundTasks for Backup

## Status: Accepted

## Context

Backup operations (incremental sync to cloud) can take seconds to minutes depending on data volume and network speed. The API should return immediately (202 Accepted) while the backup runs asynchronously.

Options:
- **FastAPI `BackgroundTasks`** — in-process background function execution
- **Celery + Redis** — distributed task queue
- **Python `asyncio.create_task`** — unmanaged coroutine
- **`subprocess`** — external process

## Decision

Use FastAPI's built-in `BackgroundTasks` for backup execution.

## Consequences

- **Simplicity** — no external dependencies (Redis, message broker). Works with the existing FastAPI app.
- **Single-user fit** — only one backup can run at a time per config. No queue, no workers needed.
- **Lifecycle** — background tasks run in the same process. If the server shuts down mid-backup, the snapshot is marked `failed` on next startup via a startup event check.
- **No persistence** — if the process crashes, the in-flight task is lost. Acceptable because the snapshot status is tracked in DB and will appear as `in_progress` → `failed` on restart.
- **Scalability limit** — not suitable for high concurrency. Acceptable for single-user.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| Celery + Redis | Massive overkill for a single-user app; adds system dependencies |
| `asyncio.create_task` | No integration with FastAPI's lifecycle; task can be garbage collected; no built-in way to track completion |
| `subprocess` | Adds complexity for IPC; no benefit over in-process execution |
