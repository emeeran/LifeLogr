# Domain Model — LifeLogr

## Overview
A single-user, offline-first daily journaling application for Linux, replicating the core experience of the Diarium app. Entries are date-bound, taggable, support inline media attachments, voice recordings with local transcription, and incremental cloud backup.

---

## Bounded Contexts

### 1. Journal Context
**Responsibility:** Manages the lifecycle of journal entries — creation, editing, deletion, and date-based retrieval. Supports calendar, list, and search views for navigation.

**Owned Data:**
- `Entry` — a single journal record for a given date
- `EntryBody` — the text content of an entry (supports markdown)
- `EntryMetadata` — created-at, updated-at timestamps, mood

**Key Rules:**
- One entry per calendar date (invariant)
- Entries are soft-deleted only (immutable once deleted)
- An entry's date is immutable after creation
- Entry body may be empty if the entry has media or a voice recording
- Supports daily prompts and mood tracking (Diarium parity)

### 2. Tagging Context
**Responsibility:** Organises entries through user-defined tags for filtering and retrieval.

**Owned Data:**
- `Tag` — a label with a unique name, supporting hierarchical paths (e.g. `travel/europe`)
- `EntryTag` — the association between an entry and a tag

**Key Rules:**
- Tag names are unique (case-insensitive)
- Tags are hierarchical — parent/child relationships allowed
- A tag can be applied to zero or more entries
- An entry can have zero or more tags
- Deleting a tag removes it from all associated entries (does not delete entries)

### 3. Media Context
**Responsibility:** Handles file-based media (images, videos, documents) attached inline to journal entries.

**Owned Data:**
- `MediaAttachment` — a reference to a stored file linked to an entry
- `MediaFile` — the actual binary blob stored on disk

**Key Rules:**
- Media belongs to exactly one entry
- Maximum file size: 25 MB per attachment
- Media is embedded inline in the entry body
- Supported types: images, videos, documents (exact list TBD)
- Deleting an entry cascades deletion to all its media

### 4. Voice Recording Context
**Responsibility:** Captures, stores, and transcribes voice-recorded journal entries.

**Owned Data:**
- `VoiceRecording` — an audio blob linked to an entry
- `Transcription` — text derived from a voice recording (optional)

**Key Rules:**
- A recording belongs to exactly one entry
- Audio format: mp3 or mp4
- Transcription is user-triggered (not automatic)
- Transcription runs locally on-device
- Transcribed text may be appended to the entry body

### 5. Backup Context
**Responsibility:** Synchronises journal data to cloud storage for persistence and recovery.

**Owned Data:**
- `BackupSnapshot` — a point-in-time incremental export of the journal
- `BackupConfig` — cloud provider credentials and sync preferences

**Key Rules:**
- Backups are user-initiated or scheduled
- Backup is incremental (not full-snapshot)
- Backup includes entries, tags, media, and recordings
- Restore replaces local data with backup data (atomic — full success or full rollback)
- Supported providers: Google Drive, OneDrive, Dropbox, WebDAV, NAS
- Authentication via app password

---

## Ubiquitous Language Glossary

| Term | Definition |
|------|-----------|
| **Journal** | The complete collection of all entries belonging to the single user |
| **Entry** | A single journal record bound to a specific calendar date |
| **Entry Body** | The textual content of a journal entry, supporting markdown formatting |
| **Entry Date** | A unique calendar date (DD-MM-YYYY) to which exactly one entry belongs |
| **Mood** | An optional emotional indicator attached to an entry |
| **Daily Prompt** | An optional writing prompt offered when creating a new entry |
| **Tag** | A user-defined hierarchical label used to categorise and filter entries |
| **Media Attachment** | A file (image, video, document) linked inline to a journal entry |
| **Voice Recording** | An audio capture associated with a journal entry |
| **Transcription** | Text converted from a voice recording via local speech-to-text |
| **Backup** | An incremental synchronised copy of journal data stored on cloud storage |
| **Restore** | The act of atomically replacing local data with data from a backup |
| **Soft Delete** | Marking an entry as deleted without removing it from storage |
| **Sync State** | The record of the last successful backup, used to determine the next incremental delta |
| **Cloud Drive** | An external storage target for backups (Google Drive, OneDrive, Dropbox, WebDAV, or NAS) |

---

## Core Aggregates

### Aggregate: Journal
- **Root Entity:** `Journal` — the user's complete diary
- **Invariants:**
  1. A journal belongs to exactly one user (single-user, offline-first)

### Aggregate: Entry
- **Root Entity:** `Entry`
- **Invariants:**
  1. One entry per calendar date — no duplicates
  2. Entry body must not be empty unless the entry has media or a voice recording
  3. An entry's date is immutable after creation
  4. Deleting an entry cascades to its tag associations, media, and recordings

### Aggregate: Tag
- **Root Entity:** `Tag`
- **Invariants:**
  1. Tag name is unique (case-insensitive)
  2. Deleting a tag dissociates it from all entries but does not delete the entries

### Aggregate: Media Attachment
- **Root Entity:** `MediaAttachment`
- **Invariants:**
  1. Media belongs to exactly one entry
  2. Maximum file size per attachment is 25 MB
  3. Entry deletion cascades to media

### Aggregate: Voice Recording
- **Root Entity:** `VoiceRecording`
- **Invariants:**
  1. A recording belongs to exactly one entry
  2. Transcription is user-triggered and runs locally

### Aggregate: Backup Snapshot
- **Root Entity:** `BackupSnapshot`
- **Invariants:**
  1. A snapshot represents a consistent incremental delta of the journal
  2. Restore is atomic — full success or full rollback

---

## Design Decisions (Resolved)

| Decision | Resolution |
|----------|-----------|
| Rich text support | Markdown |
| Tag structure | Hierarchical (e.g. `travel/europe`) |
| Max media size | 25 MB per attachment |
| Media placement | Inline in entry body |
| Transcription trigger | User-initiated |
| Transcription engine | Local / on-device |
| Cloud providers | Google Drive, OneDrive, Dropbox, WebDAV, NAS |
| Backup strategy | Incremental |
| User model | Single user, offline-first |
| Diarium feature parity | Full replication (prompts, moods, all views) |
| Navigation views | Calendar, list, and search |
| Cloud auth method | App password |
