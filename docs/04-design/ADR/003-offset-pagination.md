# ADR-003: Offset Pagination for List Endpoints

## Status: Accepted

## Context

List endpoints (`GET /entries`, `GET /entries/search`, `GET /backup/snapshots`) must return paginated results. Two common strategies:

- **Offset pagination** — `offset` + `limit` params; `SELECT ... LIMIT limit OFFSET offset`
- **Cursor pagination** — opaque cursor token; `SELECT ... WHERE id > cursor LIMIT limit`

Options evaluated based on the app's characteristics: single user, moderate data volume (one entry per day = ~365/year), SQLite backend.

## Decision

Use offset pagination (`offset` + `limit`) for all paginated endpoints.

## Consequences

- **Simplicity** — offset/limit is intuitive, easy to implement, and maps directly to SQL `LIMIT`/`OFFSET`.
- **Jump-to-page** — offset pagination allows arbitrary page access (e.g., "go to page 5"), which cursor pagination does not.
- **Performance** — for the expected data volume (hundreds to low thousands of entries), SQLite handles offset queries efficiently. No index optimization needed at this scale.
- **Consistency** — offset pagination can skip/duplicate items if data changes between page fetches. Acceptable for a single-user journal where concurrent writes are rare and the user typically browses sequentially.
- **Bounded endpoints** — `GET /tags` (tree) and `GET /entries/calendar/{y}/{m}` (max 31 entries) are not paginated because they return bounded result sets.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| Cursor pagination | Adds complexity (opaque tokens, encoding/decoding); unnecessary at single-user scale. Better suited for high-volume APIs with real-time data changes |
