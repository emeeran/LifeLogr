# Requirements — Diarilinux

> Phase 1: Requirements derived from [DOMAIN.md](../00-domain/DOMAIN.md).
> All requirements trace to domain concepts. No invented requirements.

---

## Resolved Clarifications

All `⚠️ NEEDS_CLARIFICATION` items from DOMAIN.md have been resolved and are reflected below:

| Item | Resolution |
|------|-----------|
| Rich text support | Markdown (FR-005) |
| Tag structure | Hierarchical (FR-009) |
| Max media size | 25 MB (NFR-004) |
| Media placement | Inline in entry body (FR-013) |
| Transcription trigger | User-initiated (FR-017) |
| Transcription engine | Local / on-device (FR-017) |
| Cloud providers | Google Drive, OneDrive, Dropbox, WebDAV, NAS (FR-020) |
| Backup strategy | Incremental (FR-021) |
| User model | Single user, offline-first (NFR-001) |
| Diarium parity | Full replication including prompts and moods (FR-006, FR-007) |
| Navigation views | Calendar, list, and search (FR-003, FR-004) |
| Cloud auth | App password (FR-019) |

---

## Functional Requirements

### Journal Context

| ID | Priority | Requirement | Acceptance |
|----|----------|-------------|------------|
| FR-001 | MUST | **Create entry** — allow the user to create one journal entry per calendar date | Entry is persisted with a unique date; second create for the same date is rejected |
| FR-002 | MUST | **Edit entry** — allow the user to modify the body and metadata of an existing entry | Updated body and `updated_at` timestamp are persisted |
| FR-003 | MUST | **Delete entry** — soft-delete an entry, marking it as deleted without removing storage | Entry is flagged `deleted=true`; it no longer appears in normal views but remains in storage |
| FR-004 | MUST | **Browse entries** — provide calendar, list, and search views for navigating entries | User can switch between calendar, chronological list, and full-text search; all return matching entries |
| FR-005 | MUST | **Markdown body** — entry body supports Markdown formatting | Markdown is rendered to HTML for display; raw Markdown is stored |
| FR-006 | SHOULD | **Daily prompt** — offer an optional writing prompt when creating a new entry | A prompt is displayed on entry creation; user may dismiss it |
| FR-007 | SHOULD | **Mood tracking** — allow the user to attach a mood indicator to an entry | Mood value is persisted with the entry; visible in entry detail and list views |

### Tagging Context

| ID | Priority | Requirement | Acceptance |
|----|----------|-------------|------------|
| FR-008 | MUST | **Create tag** — allow the user to create a tag with a unique name | Tag is persisted; duplicate name (case-insensitive) is rejected |
| FR-009 | MUST | **Hierarchical tags** — support parent/child tag paths (e.g. `travel/europe`) | Tags can be nested; browsing shows the hierarchy |
| FR-010 | MUST | **Tag entries** — associate one or more tags with an entry | Entry-tag association is persisted; entry appears in tag-filtered views |
| FR-011 | MUST | **Delete tag** — remove a tag and dissociate it from all entries | Tag is removed; associated entries remain untouched |
| FR-012 | MUST | **Filter by tag** — retrieve all entries matching one or more tags | Query returns only entries bearing the specified tag(s) |

### Media Context

| ID | Priority | Requirement | Acceptance |
|----|----------|-------------|------------|
| FR-013 | MUST | **Attach media inline** — embed a media file (image, video, document) inline within the entry body | File is stored; a reference is embedded in the entry body at the insertion point |
| FR-014 | MUST | **View media** — render inline media within the entry display | Attached images/videos/documents are rendered inline when viewing an entry |
| FR-015 | MUST | **Delete media** — remove a media attachment from an entry | File is deleted from storage; reference is removed from entry body |
| FR-016 | MUST | **Cascade on entry delete** — remove all media when an entry is soft-deleted | All media files belonging to a deleted entry are removed from storage |

### Voice Recording Context

| ID | Priority | Requirement | Acceptance |
|----|----------|-------------|------------|
| FR-017 | MUST | **Record voice** — capture audio (mp3/mp4) and attach it to an entry | Audio file is stored and linked to the entry |
| FR-018 | MUST | **Transcribe recording** — user-triggered local speech-to-text transcription of a recording | Transcription runs on-device; resulting text is appended to the entry body |

### Backup Context

| ID | Priority | Requirement | Acceptance |
|----|----------|-------------|------------|
| FR-019 | MUST | **Configure backup** — set cloud provider credentials using an app password | Credentials are validated and stored securely; connection test succeeds |
| FR-020 | MUST | **Support multiple providers** — Google Drive, OneDrive, Dropbox, WebDAV, NAS | User can select any supported provider; backup works identically across all |
| FR-021 | MUST | **Incremental backup** — sync only data changed since the last backup | Backup transfers only new/modified entries and media; sync state is recorded |
| FR-022 | MUST | **Restore from backup** — atomically replace local data with cloud backup data | Restore succeeds fully or rolls back completely; local state matches backup after restore |
| FR-023 | SHOULD | **Scheduled backup** — allow the user to configure automatic backup intervals | Backups run at configured intervals without manual intervention |

---

## Non-Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| NFR-001 | MUST | **Offline-first** — all core features work without network; backup syncs when connectivity is restored |
| NFR-002 | MUST | **Response time** — entry CRUD operations complete in < 200 ms on local SQLite |
| NFR-003 | MUST | **Data retention** — soft-deleted entries are retained for 30 days before permanent removal |
| NFR-004 | MUST | **Input validation** — reject media uploads > 25 MB; reject empty entry bodies (unless media or recording present) |
| NFR-005 | MUST | **Security** — cloud credentials stored encrypted at rest; never logged or exposed in API responses |
| NFR-006 | SHOULD | **Single-user constraint** — no authentication required for local use; app password only for cloud provider auth |
| NFR-007 | SHOULD | **Portability** — SQLite database is a single file that can be manually copied or moved |
| NFR-008 | COULD | **Accessibility** — UI meets WCAG 2.1 AA for entry creation and viewing |

---

## User Stories

### Journal

| ID | Story | Maps to |
|----|-------|---------|
| US-001 | As a journaler, I want to create a daily entry so that I can record my thoughts for that day. | FR-001 |
| US-002 | As a journaler, I want to edit a past entry so that I can correct or add to my reflections. | FR-002 |
| US-003 | As a journaler, I want to browse entries by calendar date so that I can quickly find a specific day. | FR-004 |
| US-004 | As a journaler, I want to search entries by keyword so that I can find all mentions of a topic. | FR-004 |
| US-005 | As a journaler, I want to format my entries with Markdown so that my journal is readable and structured. | FR-005 |
| US-006 | As a journaler, I want to receive a daily writing prompt so that I am inspired to write. | FR-006 |
| US-007 | As a journaler, I want to record my mood each day so that I can track emotional patterns over time. | FR-007 |

### Tagging

| ID | Story | Maps to |
|----|-------|---------|
| US-008 | As a journaler, I want to tag entries with hierarchical labels so that I can organise by topic and sub-topic. | FR-009, FR-010 |
| US-009 | As a journaler, I want to filter entries by tag so that I can view all entries on a given topic. | FR-012 |

### Media

| ID | Story | Maps to |
|----|-------|---------|
| US-010 | As a journaler, I want to attach photos and documents inline in my entries so that my journal is visually rich. | FR-013, FR-014 |
| US-011 | As a journaler, I want inline media to be cleaned up when I delete an entry so that orphan files don't waste storage. | FR-016 |

### Voice

| ID | Story | Maps to |
|----|-------|---------|
| US-012 | As a journaler, I want to record a voice memo and attach it to my entry so that I can journal hands-free. | FR-017 |
| US-013 | As a journaler, I want to transcribe my voice recordings locally so that my audio entries become searchable text. | FR-018 |

### Backup

| ID | Story | Maps to |
|----|-------|---------|
| US-014 | As a journaler, I want to back up my journal to my preferred cloud provider so that my data is safe. | FR-019, FR-020, FR-021 |
| US-015 | As a journaler, I want to restore my journal from a backup so that I can recover after data loss. | FR-022 |
| US-016 | As a journaler, I want automatic scheduled backups so that I don't have to remember to sync manually. | FR-023 |

---

## Out of Scope (v1)

1. **Multi-user support** — the app is single-user and local-first; user accounts, authentication, and permissions are not needed.
2. **Real-time collaboration** — no concurrent editing, sharing, or social features.
3. **Rich-text WYSIWYG editor** — Markdown is the formatting model; a visual editor may come in a later version.
4. **Cross-platform clients** — Linux desktop is the sole target; mobile, web, and other OS clients are excluded.
5. **Plugin/extension system** — no third-party extension points in v1.
6. **Import from other journal apps** — only Diarium parity is in scope; bulk migration tools are deferred.
