# ADR-002: No Authentication for Local Endpoints

## Status: Accepted

## Context

The app is single-user, running on the user's local machine. All journal, tag, media, and voice recording endpoints operate on local data with no network exposure. Cloud backup endpoints need provider credentials but those are stored in the database (encrypted), not sent as request headers.

Options evaluated:
- **No auth** — all local endpoints are open; backup uses stored credentials
- **API key / Bearer token** — single hardcoded or configured token for all endpoints
- **Session-based auth** — login flow with cookies

## Decision

No authentication middleware. All endpoints are unauthenticated at the application level. Cloud provider credentials are stored encrypted in `backup_config` and used internally by the `BackupService` — they are never passed as request auth headers.

## Consequences

- **Simplicity** — no login flow, no token management, no password hashing.
- **Security model** — relies on OS-level access control (the user's machine). If someone has access to the machine, they have access to the journal — same as any local desktop app.
- **Backup auth** — cloud provider credentials (app passwords) are stored encrypted at rest (AES-256-GCM, NFR-005) and decrypted only when needed for backup/restore operations.
- **Future multi-user** — if multi-user support is ever added, auth middleware would need to be introduced at that time.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| API key / Bearer token | Adds friction for zero security benefit on a single-user local app |
| Session-based auth | Requires login flow, session storage, and cookie management — unjustified complexity |
