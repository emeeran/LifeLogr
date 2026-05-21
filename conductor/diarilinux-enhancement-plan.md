# Diarilinux Enhancement Plan

> **Version:** 3.0
> **Date:** 2026-05-10
> **Status:** DRAFT — Pending Approval
> **Scope:** 22 features across 7 phases, touching every layer: FastAPI backend, SQLite schema, and future Vue frontend.

---

## Table of Contents

1. [Background & Motivation](#1-background--motivation)
2. [Current State Assessment](#2-current-state-assessment)
3. [Scope & Impact](#3-scope--impact)
4. [Feature Inventory](#4-feature-inventory)
5. [Phased Implementation Plan](#5-phased-implementation-plan)
6. [Database Schema Changes](#6-database-schema-changes)
7. [New API Endpoints](#7-new-api-endpoints)
8. [New Dependencies](#8-new-dependencies)
9. [Testing Strategy](#9-testing-strategy)
10. [Risk Assessment](#10-risk-assessment)
11. [Alternatives Considered](#11-alternatives-considered)
12. [Traceability Matrix](#12-traceability-matrix)
13. [Appendix A — Final File Structure](#appendix-a--final-file-structure)
14. [Appendix B — Per-Phase Implementation Order](#appendix-b--per-phase-implementation-order)

---

## 1. Background & Motivation

The goal is to transition the current DiariumLinux journal application into a robust, fully-featured, and secure platform named **Diarilinux**. This involves implementing advanced AI integrations (local Ollama, OCR), enhanced security (encryption), rich multimedia support, and advanced organizational tools (Geotagging, Version History, Analytics) — all while preserving the strict offline-first, privacy-focused architecture.

---

## 2. Current State Assessment

### What Exists (Backend — Fully Implemented)

| Layer | Components |
|-------|-----------|
| **Models** | `Entry`, `Tag`, `EntryTag`, `Media`, `VoiceRecording`, `BackupConfig`, `BackupSnapshot`, `DailyPrompt` |
| **Routers** | `entries`, `tags`, `media`, `recordings`, `backup`, `prompts` |
| **Services** | `EntryService`, `TagService`, `MediaService`, `RecordingService`, `BackupService`, `PromptService` |
| **Core** | `config` (pydantic-settings), `database` (async SQLAlchemy), `security` (AES-256-GCM) |
| **Features** | CRUD entries, hierarchical tags, media upload/download, voice recording + transcription stub, backup config + export/import, daily prompts, markdown zip export, soft-delete, calendar view, ILIKE search |
| **Tests** | Unit tests for all services + security |
| **Docs** | DOMAIN.md, CONTEXT_MAP.md, REQUIREMENTS.md, SPEC.md, REVIEW.md (PASS), DESIGN.md, 6 ADRs |

### What Does NOT Exist

- **No frontend** — the application is API-only
- **No Ollama integration** — no AI grammar/spell-check or text-rewriting
- **No encryption of entry content** — only backup credentials are encrypted
- **No version history / revisions** — entries are overwritten on update
- **No geotagging** — no location data stored
- **No OCR** — no text extraction from images
- **No plugin architecture** — no extensibility API
- **No analytics dashboard** — no statistics endpoints
- **No reminder/notification system** — no scheduling
- **No full-text index** — search uses `ILIKE` pattern matching
- **No PDF/HTML export** — only markdown zip export exists
- **No automated backup scheduling** — backup is manual only
- **No offline sync queue** — no conflict resolution for reconnection
- **No emoji picker** — frontend concern
- **No text alignment toolbar** — frontend concern
- **No brand/logo** — app name is "diary" in FastAPI title

### Architecture Constraints

- **Offline-first, single-user** — no auth middleware
- **SQLite** — limits concurrency; FTS5 available for full-text indexing
- **FastAPI BackgroundTasks** — no Celery/Redis; acceptable for single-user
- **`cryptography` library** already available for AES-256-GCM

---

## 3. Scope & Impact

This overhaul touches every layer of the application:

- **Frontend (Vue):** UI/UX redesign, rebranding, double-click interactions, editor toolbar enhancements (alignment, emoji), analytics dashboard, and plugin management interface.
- **Backend (FastAPI):** New endpoints and services for Ollama, OCR, encryption, version history, analytics, reminders, export, sync, and plugins.
- **Database (SQLite):** Schema updates to support versioning (`entry_revisions`), geotags, encryption metadata, OCR cache, reminders, sync queues, plugin registrations, and a FTS5 search index.
- **System Architecture:** Hardening the offline-first architecture with robust background sync, automated encrypted backups, and E2E cloud provider adapters.

---

## 4. Feature Inventory

| # | Feature | Category | Backend Impact | New Dependencies | Phase |
|---|---------|----------|---------------|-------------------|-------|
| F01 | Double-click to edit (calendar/timeline) | UI Interaction | None (frontend only) | — | P1 |
| F02 | Ollama integration (grammar, spell-check, rewrite) | AI | New router + service | `httpx` (move from dev-dep) | P2 |
| F03 | Toolbar alignment options (L/R/C/J) | UI | None (frontend only) | — | P1 |
| F04 | Rebrand to "Diarilinux" + logo | Branding | Config + main.py title | — | P1 |
| F05 | Emoji support | UI | None (frontend only) | — | P1 |
| F06 | Encryption/decryption of notes and selected text | Security | New router + service | `cryptography` (exists) | P3 |
| F07 | File attachments to notes | Media | Extend existing Media model | — | P4 |
| F08 | Geotagging | Metadata | New fields on Entry | — | P4 |
| F09 | Audio and video notes | Multimedia | New model + extend media | — | P4 |
| F10 | Global search (date, tags, content type) | Search | New router + service | — | P5 |
| F11 | Offline mode + background sync | Sync | New sync queue model | — | P7 |
| F12 | E2E encrypted cloud sync | Sync | Extend backup service | Provider SDKs | P7 |
| F13 | Version history (Time Machine) | Data | New revision model + service | — | P3 |
| F14 | OCR from images | AI | New router + service | `pytesseract` + `Pillow` | P2 |
| F15 | Voice-to-text (speech-to-text) | AI | Already stubbed (Whisper) | `faster-whisper` | P2 |
| F16 | Plugin architecture | Platform | New models + API + hook system | Plugin loading mechanism | P7 |
| F17 | Full-text search engine | Search | FTS5 virtual table + triggers | — | P5 |
| F18 | Export (PDF, Markdown, HTML) | Export | New service | `weasyprint`, `markdown-it-py` | P6 |
| F19 | Automated encrypted backups | Backup | Scheduler + payload encryption | `APScheduler` | P6 |
| F20 | Hierarchical tagging (finalized) | Organization | Already implemented | — | Done |
| F21 | Statistics and analytics dashboard | Analytics | New router + service | — | P5 |
| F22 | Reminder notifications | Notifications | New model + scheduler | `APScheduler`, desktop notify | P6 |

---

## 5. Phased Implementation Plan

### Phase 1: Rebranding & Core UI

**Goal:** Rename the application, create brand identity, and prepare API surface for frontend features.

#### 1.1 Rebranding — F04

**Files to modify:**
- `backend/app/core/config.py` — Add `APP_NAME: str = "Diarilinux"`
- `backend/app/main.py` — Update `title="Diarilinux"`, description
- `backend/pyproject.toml` — Update `name = "diarilinux"`
- `CLAUDE.md` — Update project purpose section
- `docs/` — Update all SDD artifacts to reference "Diarilinux"

**Logo:**
- Create `assets/diarilinux-logo.svg` — feather pen + Tux-inspired elements
- Expose via `StaticFiles` mount in `main.py` for `/static`
- Add `GET /api/v1/brand/logo` endpoint for API consumers

#### 1.2 Double-Click Editor Launch — F01
- **Backend:** No changes. Frontend handles `dblclick` events on calendar/timeline cells.
- **API note:** `GET /api/v1/entries/{entry_id}` already returns full body for editor hydration.

#### 1.3 Toolbar Alignment Options — F03
- **Backend:** No changes. Alignment is stored in the markdown body via HTML `<div style="text-align: ...">` or markdown-it plugins. The `body` field is already a free-text string.

#### 1.4 Emoji Support — F05
- **Backend:** No changes. Emoji are Unicode characters stored directly in `body`. SQLite handles UTF-8 natively.

**Phase 1 Deliverables:**
- [ ] App renamed to "Diarilinux" across all files
- [ ] SVG logo created and served statically
- [ ] `pyproject.toml` and config updated
- [ ] All SDD docs reference "Diarilinux"

---

### Phase 2: AI & Advanced Processing

**Goal:** Integrate Ollama for text assistance, OCR for image text extraction, and finalize voice-to-text.

#### 2.1 Ollama Integration — F02

**New files:**
- `backend/app/routers/ai.py`
- `backend/app/services/ollama_service.py`
- `backend/app/schemas/ai.py`

**New config settings:**
```python
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MODEL: str = "llama3"
OLLAMA_TIMEOUT_SECONDS: int = 120
```

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/ai/grammar-check` | Check grammar and spelling |
| POST | `/api/v1/ai/spell-check` | Spell-check only |
| POST | `/api/v1/ai/rewrite` | Rewrite text with specified tone/style |
| GET | `/api/v1/ai/status` | Check if Ollama is running + model available |

**Schemas:**
```python
class GrammarCheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    language: str = Field(default="en", max_length=5)

class GrammarCheckResponse(BaseModel):
    original_text: str
    corrected_text: str
    suggestions: list[Suggestion]

class Suggestion(BaseModel):
    offset: int
    length: int
    original: str
    suggestion: str
    rule_id: str
    message: str

class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    style: str = Field(description="formal, casual, concise, elaborate, creative")
    instructions: str | None = Field(default=None, max_length=500)

class RewriteResponse(BaseModel):
    original_text: str
    rewritten_text: str
    style: str
```

**Service Logic (`OllamaService`):**
- Connect to local Ollama at `OLLAMA_BASE_URL`
- Structured prompts for grammar-checking: identify errors, return JSON
- For rewriting: send text with style instruction
- Graceful degradation when Ollama is unavailable (503 Service Unavailable)
- Cache model availability check (avoid hitting `/api/tags` on every request)

#### 2.2 OCR Integration — F14

**New files:**
- `backend/app/services/ocr_service.py`
- Add OCR endpoints to `backend/app/routers/media.py`

**New config settings:**
```python
OCR_ENGINE: str = "tesseract"
TESSERACT_CMD: str | None = None  # path override
```

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/media/{media_id}/ocr` | Extract text from an image |
| GET | `/api/v1/media/{media_id}/ocr` | Get cached OCR result |

**Schema:**
```python
class OCRResponse(BaseModel):
    media_id: int
    extracted_text: str
    confidence: float
    language: str
    processed_at: datetime
```

**Service Logic (`OCRService`):**
- Validate `media_type` starts with `image/`
- Run Tesseract via `pytesseract`
- Cache results in `ocr_results` table
- Support language parameter for multilingual OCR

#### 2.3 Voice-to-Text — F15

**Current state:** `VoiceRecordingService.transcribe()` is a stub. `ADR/006-whisper-local-transcription.md` exists.

**Implementation:**
- Complete the `transcribe()` method in `recording_service.py`
- Use `faster-whisper` (faster, less VRAM than `openai-whisper`)
- Load model on first call (lazy init)
- Save transcription to `voice_recordings.transcription`
- Append transcription text to entry body (with separator)

**New config settings:**
```python
WHISPER_MODEL: str = "base"  # tiny, base, small, medium, large
WHISPER_DEVICE: str = "cpu"  # cpu or cuda
```

**Phase 2 Deliverables:**
- [ ] Ollama service: grammar-check, spell-check, rewrite
- [ ] OCR service with text extraction from images
- [ ] Whisper transcription fully implemented
- [ ] AI status endpoint
- [ ] Graceful degradation when AI services unavailable
- [ ] Unit + integration tests for all AI features

---

### Phase 3: Security & Data Integrity

**Goal:** Implement content encryption and version history.

#### 3.1 Encryption/Decryption — F06

**New files:**
- `backend/app/routers/encryption.py`
- `backend/app/services/encryption_service.py`
- `backend/app/schemas/encryption.py`

**Approach:** Extend existing `app/core/security.py` (already has AES-256-GCM). Two modes:
1. **Full entry encryption** — encrypt the entire `body` field at rest
2. **Selection encryption** — encrypt a substring within the body

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/encryption/encrypt-entry/{entry_id}` | Encrypt entire entry body |
| POST | `/api/v1/encryption/decrypt-entry/{entry_id}` | Decrypt entry (returns plaintext; stays encrypted at rest) |
| POST | `/api/v1/encryption/encrypt-selection` | Encrypt a text selection |
| POST | `/api/v1/encryption/decrypt-selection` | Decrypt a ciphertext selection |
| GET | `/api/v1/encryption/status/{entry_id}` | Check if entry is encrypted |

**Schemas:**
```python
class EncryptSelectionRequest(BaseModel):
    plaintext: str = Field(min_length=1)
    key_hint: str | None = Field(default=None, max_length=100)

class DecryptSelectionRequest(BaseModel):
    ciphertext: str = Field(min_length=1)

class EncryptionStatusResponse(BaseModel):
    entry_id: int
    is_encrypted: bool
    encrypted_at: datetime | None
```

**Service Logic (`EncryptionService`):**
- `encrypt_entry()` — Replace `body` with AES-256-GCM ciphertext (base64). Set `is_encrypted=True`
- `decrypt_entry()` — Decrypt in-memory for display; body stays encrypted in DB
- `encrypt_selection()` — Frontend embeds ciphertext with marker `<!--ENC{base64}-->`
- `decrypt_selection()` — Decrypt embedded ciphertext
- Key derivation: Use `SECRET_KEY` stretched with PBKDF2 for entry-level encryption

#### 3.2 Version History (Time Machine) — F13

**New files:**
- `backend/app/routers/revisions.py`
- `backend/app/services/revision_service.py`
- `backend/app/schemas/revision.py`
- `backend/app/models/revision.py`

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/entries/{entry_id}/revisions` | List all revisions for an entry |
| GET | `/api/v1/entries/{entry_id}/revisions/{rev_id}` | Get a specific revision |
| POST | `/api/v1/entries/{entry_id}/revisions/{rev_id}/restore` | Restore entry to this revision |
| GET | `/api/v1/entries/{entry_id}/revisions/diff?from=X&to=Y` | Diff between two revisions |
| DELETE | `/api/v1/entries/{entry_id}/revisions` | Purge revision history |

**Schemas:**
```python
class RevisionResponse(BaseModel):
    id: int
    entry_id: int
    revision_number: int
    title: str | None
    body: str
    mood: str | None
    snapshot_reason: str  # edit, manual, restore
    created_at: datetime

class RevisionDiffResponse(BaseModel):
    from_revision: int
    to_revision: int
    title_diff: str | None
    body_diff: str  # unified diff format
    mood_changed: bool
```

**Service Logic (`RevisionService`):**
- Auto-create revision on every entry update (hook into `EntryService.update()`)
- Manual snapshots via `snapshot_reason='manual'`
- Restore: copy revision data back to entry, create new revision with reason `'restore'`
- Diff: Python `difflib.unified_diff`
- Purge: delete revisions older than N days (configurable retention)

**Integration point:** Modify `EntryService.update()` to call `RevisionService.create_snapshot()` before applying changes.

**Phase 3 Deliverables:**
- [ ] Encryption service (entry-level + selection-level)
- [ ] Revision model and Alembic migration
- [ ] Revision service with auto-snapshot on edit
- [ ] Revision diff and restore endpoints
- [ ] Unit tests for encryption roundtrip
- [ ] Unit tests for revision create/diff/restore

---

### Phase 4: Organization, Metadata & Multimedia

**Goal:** Add geotagging, finalize file attachments, and support audio/video notes.

#### 4.1 Geotagging — F08

**Schema changes:** Add to `EntryCreate`, `EntryUpdate`, `EntryResponse`:
- `latitude: float | None`, `longitude: float | None`, `location_name: str | None`

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/entries/map` | All entries with geodata (map view) |
| GET | `/api/v1/entries/nearby?lat=X&lon=Y&radius_km=10` | Entries near a location |

**Service:** Haversine formula for `nearby` queries. Add geofiltering to `list_entries()`.

#### 4.2 File Attachments — F07

**Current state:** Media attachment already exists with upload/download/delete. `Media` model supports `image/video/document/audio` types.

**Enhancements:**
- Add `is_inline: bool` to `Media` model (distinguish inline vs attached)
- Batch upload endpoint
- Make max file size configurable per type

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/media/batch` | Upload multiple files at once |
| GET | `/api/v1/entries/{entry_id}/attachments` | List all attachments for an entry |

#### 4.3 Multimedia Notes (Audio & Video) — F09

**Current state:** `VoiceRecording` model exists for audio. `Media` model supports `video` type.

**Enhancements:**
- Add `VideoNote` model (analogous to `VoiceRecording`)
- Auto-generate thumbnails for video uploads
- Support video transcription (extract audio, run through Whisper)

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/videos` | Upload a video note |
| POST | `/api/v1/videos/{video_id}/transcribe` | Transcribe video audio |
| GET | `/api/v1/videos/{video_id}/thumbnail` | Get video thumbnail |
| DELETE | `/api/v1/videos/{video_id}` | Delete a video note |

**Phase 4 Deliverables:**
- [ ] Geotagging fields on Entry model + map/nearby endpoints
- [ ] Batch media upload + inline/attachment distinction
- [ ] VideoNote model + endpoints
- [ ] Video thumbnail generation
- [ ] Tests for all new features

---

### Phase 5: Search, Indexing & Analytics

**Goal:** Replace ILIKE search with FTS5, add global multi-dimensional search, and build analytics endpoints.

#### 5.1 Full-Text Search Engine — F17

Replace `ILIKE` pattern matching with SQLite FTS5:

```sql
CREATE VIRTUAL TABLE entries_fts USING fts5(
    title, body, mood, tags,
    content='entries', content_rowid='id'
);
```

With INSERT / UPDATE / DELETE triggers to keep the FTS index in sync with tag names joined from `entry_tags` + `tags`.

**Service changes:** Replace `EntryService.search()` with FTS5 `MATCH`. Support `AND`, `OR`, `NOT`, `*` (wildcard), `"exact phrase"`.

#### 5.2 Global Search — F10

**New files:**
- `backend/app/routers/search.py`
- `backend/app/services/search_service.py`
- `backend/app/schemas/search.py`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/search` | Global search across all content types |

**Query parameters:** `q`, `types` (entries/media/tags), `tags`, `date_from`/`date_to`, `mood`, `has_media`, `has_location`, `offset`/`limit`.

#### 5.3 Statistics & Analytics — F21

**New files:**
- `backend/app/routers/analytics.py`
- `backend/app/services/analytics_service.py`
- `backend/app/schemas/analytics.py`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/analytics/overview` | Total entries, words, media, tags, streaks |
| GET | `/api/v1/analytics/writing-habits` | Entry frequency per week/month/day-of-week, averages |
| GET | `/api/v1/analytics/word-counts` | Word count trends over time |
| GET | `/api/v1/analytics/tag-usage` | Tag distribution and usage percentages |
| GET | `/api/v1/analytics/mood-trends` | Mood distribution and trend direction |
| GET | `/api/v1/analytics/activity-heatmap` | Activity data for calendar heatmap |
| GET | `/api/v1/analytics/media-stats` | Media attachment statistics |

**Phase 5 Deliverables:**
- [ ] FTS5 virtual table with sync triggers
- [ ] Global search with multi-type, multi-filter support
- [ ] Analytics service with 7 endpoint categories
- [ ] Activity heatmap data endpoint
- [ ] Writing streak calculation
- [ ] Tests with seeded data

---

### Phase 6: Export, Backup Automation & Notifications

**Goal:** Add PDF/HTML export, automated encrypted backups, and reminder notifications.

#### 6.1 Data Export (PDF, HTML) — F18

**Current state:** Markdown zip export exists at `GET /api/v1/entries/export/markdown`.

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/entries/export/pdf` | Export entries as styled PDF |
| GET | `/api/v1/entries/export/html` | Export entries as browsable HTML archive |

**Implementation:**
- **PDF:** `weasyprint` (HTML-to-PDF) with Diarilinux-branded template, embedded media (base64)
- **HTML:** `markdown-it-py` for MD→HTML, inline CSS, index + entry pages

#### 6.2 Automated Encrypted Backups — F19

**Current state:** Manual backup trigger exists. AES-256-GCM encryption exists for credentials.

**Implementation:**
- `APScheduler` for background cron-based scheduling
- Parse `schedule_cron` from `BackupConfig` to create scheduled jobs
- Encrypt backup payload with user-provided key (separate from `SECRET_KEY`)
- Backup health check: alert if no successful backup in N days

**New config settings:**
```python
BACKUP_ENCRYPTION_KEY: str | None = None
AUTO_BACKUP_ENABLED: bool = True
BACKUP_HEALTH_CHECK_DAYS: int = 7
```

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/backup/health` | Backup health status |
| POST | `/api/v1/backup/schedule/reload` | Reload scheduler after config change |

#### 6.3 Reminder Notifications — F22

**New files:**
- `backend/app/routers/reminders.py`
- `backend/app/services/reminder_service.py`
- `backend/app/schemas/reminder.py`
- `backend/app/models/reminder.py`

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/reminders` | Create a reminder |
| GET | `/api/v1/reminders` | List all reminders |
| PATCH | `/api/v1/reminders/{id}` | Update a reminder |
| DELETE | `/api/v1/reminders/{id}` | Delete a reminder |
| POST | `/api/v1/reminders/{id}/test` | Send test notification |

**Notification delivery:**
- Desktop: `notify-send` (Linux) via subprocess
- Future: WebSocket push to frontend
- Log all notifications for audit

**Phase 6 Deliverables:**
- [ ] PDF export with branded template
- [ ] HTML export with browsable archive
- [ ] APScheduler integration for automated backups
- [ ] Backup payload encryption + health check
- [ ] Reminder CRUD + desktop notification delivery
- [ ] Tests for all new features

---

### Phase 7: Sync, Offline & Plugin Ecosystem

**Goal:** Implement offline sync queue, E2E encrypted cloud sync, and plugin architecture.

#### 7.1 Offline Mode + Background Sync — F11

**New files:**
- `backend/app/models/sync.py`
- `backend/app/services/sync_service.py`
- `backend/app/routers/sync.py`

**Logic:**
- Every write operation appends to `sync_queue`
- When connectivity is restored, `SyncService.process_queue()` pushes changes
- Conflict resolution: last-write-wins (timestamp-based) for single-user app
- Sync status endpoint for frontend connectivity indicator

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/sync/status` | Current sync status |
| POST | `/api/v1/sync/flush` | Force sync all pending operations |
| GET | `/api/v1/sync/pending` | List pending sync operations |
| DELETE | `/api/v1/sync/pending` | Clear sync queue (dangerous) |

#### 7.2 E2E Encrypted Cloud Sync — F12

**Current state:** `BackupService` supports manual backup to cloud providers.

**Enhancements:**
- Encrypt entire backup payload with user-provided key
- Provider-specific adapters:
  - Nextcloud (WebDAV) via `webdavclient3`
  - Dropbox (API v2) via `dropbox` SDK
  - Google Drive (REST API v3) via `google-api-python-client`
- Conflict detection (compare `updated_at` timestamps)
- Merge strategies: keep-local, keep-remote, keep-newest

**New endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/backup/sync/{config_id}` | Trigger two-way sync |
| GET | `/api/v1/backup/conflicts/{config_id}` | List conflicts after sync |
| POST | `/api/v1/backup/resolve-conflict` | Resolve a specific conflict |

#### 7.3 Plugin Architecture — F16

**New files:**
- `backend/app/models/plugin.py`
- `backend/app/services/plugin_service.py`
- `backend/app/routers/plugins.py`
- `backend/app/schemas/plugin.py`
- `backend/app/core/hooks.py` — Hook system for extensibility

**Hook System (`app/core/hooks.py`):**
```python
class HookManager:
    def register(self, hook_name: str, handler: Callable, plugin_id: int, priority: int = 100) -> None: ...
    def unregister(self, plugin_id: int) -> None: ...
    async def dispatch(self, hook_name: str, payload: dict) -> list[Any]: ...

# Available hooks:
# on_entry_create, on_entry_update, on_entry_delete
# on_editor_render, on_editor_toolbar
# on_search, on_export
# on_plugin_load, on_plugin_unload
```

**API Endpoints:**

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/plugins` | List installed plugins |
| POST | `/api/v1/plugins/install` | Install a plugin (file or PyPI) |
| DELETE | `/api/v1/plugins/{plugin_id}` | Uninstall a plugin |
| PATCH | `/api/v1/plugins/{plugin_id}` | Enable/disable/configure |
| GET | `/api/v1/plugins/{plugin_id}/config` | Get plugin config schema |
| POST | `/api/v1/plugins/{plugin_id}/config` | Update plugin config |
| GET | `/api/v1/plugins/hooks` | List available hooks |

**Plugin Interface (for developers):**
```python
class DiarilinuxPlugin(Protocol):
    name: str
    version: str
    description: str

    def on_load(self, config: dict) -> None: ...
    def on_unload(self) -> None: ...
    def register_hooks(self, hook_manager: HookManager) -> None: ...
```

**Phase 7 Deliverables:**
- [ ] Sync queue model + processing logic
- [ ] Sync status endpoints
- [ ] E2E encrypted payload for cloud backup
- [ ] Provider-specific adapters (WebDAV, Dropbox, Google Drive)
- [ ] Conflict detection and resolution
- [ ] Plugin model + hook system
- [ ] Plugin install/uninstall/configure API
- [ ] Plugin developer documentation
- [ ] Example hello-world plugin

---

## 6. Database Schema Changes

### New Tables

| Table | Phase | Purpose |
|-------|-------|---------|
| `ocr_results` | P2 | Cache OCR text extraction results |
| `entry_revisions` | P3 | Version history for entries |
| `video_notes` | P4 | Video note metadata + thumbnails |
| `entries_fts` | P5 | FTS5 virtual table for full-text search |
| `reminders` | P6 | Scheduled writing reminders |
| `sync_queue` | P7 | Offline change queue |
| `sync_status` | P7 | Sync state tracking |
| `plugins` | P7 | Plugin registration |
| `plugin_hooks` | P7 | Plugin hook bindings |

### Modified Tables

| Table | Phase | Changes |
|-------|-------|---------|
| `entries` | P3 | Add `is_encrypted BOOLEAN DEFAULT FALSE`, `encrypted_at DATETIME` |
| `entries` | P4 | Add `latitude REAL`, `longitude REAL`, `location_name TEXT` |
| `media` | P4 | Add `is_inline BOOLEAN DEFAULT TRUE` |

### Migration Strategy

- Use **Alembic** for all schema migrations (currently using `create_all()` for dev)
- Each phase gets a numbered migration
- FTS5 triggers created in a dedicated migration
- Add Alembic to project dependencies from Phase 3 onward

---

## 7. New API Endpoints

| Phase | Prefix | Endpoints | Count |
|-------|--------|-----------|-------|
| P1 | `/static/` | Logo, assets | 1 |
| P2 | `/api/v1/ai/` | Grammar, spell-check, rewrite, status | 4 |
| P2 | `/api/v1/media/{id}/ocr` | OCR extract, get cached | 2 |
| P3 | `/api/v1/encryption/` | Encrypt/decrypt entry, selection, status | 5 |
| P3 | `/api/v1/entries/{id}/revisions/` | List, get, restore, diff, purge | 5 |
| P4 | `/api/v1/entries/map` | Map view, nearby | 2 |
| P4 | `/api/v1/media/batch` | Batch upload | 1 |
| P4 | `/api/v1/entries/{id}/attachments` | List attachments | 1 |
| P4 | `/api/v1/videos/` | Upload, transcribe, thumbnail, delete | 4 |
| P5 | `/api/v1/search` | Global search | 1 |
| P5 | `/api/v1/analytics/` | Overview, habits, words, tags, mood, heatmap, media | 7 |
| P6 | `/api/v1/entries/export/` | PDF, HTML | 2 |
| P6 | `/api/v1/backup/health` | Health check, schedule reload | 2 |
| P6 | `/api/v1/reminders/` | CRUD, test notification | 5 |
| P7 | `/api/v1/sync/` | Status, flush, pending | 4 |
| P7 | `/api/v1/backup/sync/` | Two-way sync, conflicts, resolve | 3 |
| P7 | `/api/v1/plugins/` | List, install, uninstall, configure, hooks | 7 |
| | | **Total new endpoints** | **~56** |

---

## 8. New Dependencies

### Production Dependencies

| Package | Phase | Purpose |
|---------|-------|---------|
| `httpx` | P2 | HTTP client for Ollama API (move from dev) |
| `pytesseract` | P2 | Tesseract OCR Python wrapper |
| `Pillow` | P2 | Image preprocessing for OCR |
| `faster-whisper` | P2 | Local speech-to-text (preferred over `openai-whisper`) |
| `markdown-it-py` | P6 | Markdown to HTML conversion |
| `weasyprint` | P6 | HTML to PDF generation |
| `APScheduler` | P6 | Cron-based task scheduling |
| `alembic` | P3+ | Database migration management |
| `dropbox` | P7 | Dropbox SDK (optional) |
| `google-api-python-client` | P7 | Google Drive SDK (optional) |
| `google-auth` | P7 | Google auth (optional) |
| `webdavclient3` | P7 | WebDAV/Nextcloud client (optional) |

### System Dependencies

| Package | Phase | Purpose |
|---------|-------|---------|
| `tesseract-ocr` | P2 | OCR engine |
| `tesseract-ocr-eng` | P2 | English language data |

### Dev Dependencies

| Package | Phase | Purpose |
|---------|-------|---------|
| `pytest-cov` | All | Coverage reporting |
| `respx` | P2 | Mock httpx for Ollama tests |

---

## 9. Testing Strategy

### Per-Phase Test Requirements

| Phase | New Test Files | Est. Count |
|-------|---------------|------------|
| P1 | `test_config.py` (updated) | ~5 |
| P2 | `test_ollama_service.py`, `test_ocr_service.py`, `test_recording_service.py` (updated) | ~30 |
| P3 | `test_encryption_service.py`, `test_revision_service.py` | ~25 |
| P4 | `test_geotagging.py`, `test_video_service.py`, `test_media_service.py` (updated) | ~20 |
| P5 | `test_search_service.py`, `test_analytics_service.py` | ~25 |
| P6 | `test_export_service.py`, `test_backup_service.py` (updated), `test_reminder_service.py` | ~20 |
| P7 | `test_sync_service.py`, `test_plugin_service.py` | ~25 |

### Test Types

1. **Unit tests** — All services with mocked DB sessions
2. **Integration tests** — Full request/response cycle with test DB
3. **E2E tests** — Offline sync simulation, backup restore cycle
4. **Security tests** — Encryption roundtrip, key derivation, timing attack resistance
5. **Performance tests** — FTS5 search with 10k+ entries, analytics aggregation

### Test Infrastructure

- Use existing `pytest-asyncio` with in-memory SQLite for fast test runs
- Add `conftest.py` fixtures for seeded data (entries across multiple dates/tags/moods)
- Mock external services (Ollama, cloud providers) with `respx` / `unittest.mock`

---

## 10. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Ollama not installed/running | High | Medium | Graceful degradation (503), health-check endpoint, clear error messages |
| Whisper model download size | Medium | High | Lazy download, configurable model size (tiny→large), cache management |
| FTS5 trigger performance on bulk import | Medium | Low | Batch import mode with deferred indexing |
| Schema migration breaking existing data | High | Low | Alembic migrations with rollback, backup before migration |
| Encryption key loss | Critical | Medium | Key export feature, recovery key generation, clear warnings |
| Plugin security (arbitrary code execution) | Critical | Medium | Sandboxed execution, plugin approval process, permission system |
| Large media files in backup | Medium | High | Configurable max backup size, incremental media sync, compression |
| Cloud API rate limits | Low | Medium | Exponential backoff, rate limit headers, queue-based retries |

---

## 11. Alternatives Considered

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| AI engine | Cloud AI APIs vs Local Ollama | **Local Ollama** | Maintains strict offline-first and privacy-focused requirements. No data leaves the machine. |
| Sync model | Centralized cloud vs BYO-Cloud | **BYO-Cloud** (WebDAV/Dropbox/Google Drive) | Users retain total ownership of their data. No Diarilinux-hosted server required. |
| STT engine | Cloud STT vs Local Whisper | **Local `faster-whisper`** | Runs on-device, no API key, privacy-first. `faster-whisper` chosen over `openai-whisper` for lower VRAM and faster inference. |
| Search engine | Elasticsearch/Meilisearch vs SQLite FTS5 | **SQLite FTS5** | Zero additional infrastructure. Single-user app doesn't need a separate search server. |
| PDF generation | `reportlab` vs `weasyprint` | **`weasyprint`** | HTML-to-PDF allows CSS styling and branded templates. Simpler than programmatic PDF construction. |
| Task scheduling | Celery/Redis vs APScheduler | **APScheduler** | Single-user app; no need for distributed task queue. In-process scheduling is sufficient. |

---

## 12. Traceability Matrix

| Feature | ID | Phase | New Backend Files | New Models | New Endpoints |
|---------|----|----|-------------------|------------|---------------|
| F01 Double-click edit | — | P1 | — | — | — |
| F02 Ollama integration | NEW-FR-024 | P2 | `routers/ai.py`, `services/ollama_service.py`, `schemas/ai.py` | — | 4 |
| F03 Toolbar alignment | — | P1 | — | — | — |
| F04 Rebranding | NEW-FR-025 | P1 | `config.py`, `main.py` | — | 1 |
| F05 Emoji support | — | P1 | — | — | — |
| F06 Encryption | NEW-FR-026 | P3 | `routers/encryption.py`, `services/encryption_service.py`, `schemas/encryption.py` | — | 5 |
| F07 File attachments | FR-013 (enhanced) | P4 | `routers/media.py`, `services/media_service.py` | — | 2 |
| F08 Geotagging | NEW-FR-027 | P4 | `routers/entries.py` | — | 2 |
| F09 Audio/video notes | FR-017, NEW-FR-028 | P4 | `routers/videos.py`, `services/video_service.py` | `VideoNote` | 4 |
| F10 Global search | FR-004 (enhanced) | P5 | `routers/search.py`, `services/search_service.py`, `schemas/search.py` | — | 1 |
| F11 Offline mode | NFR-001 (enhanced) | P7 | `routers/sync.py`, `services/sync_service.py` | `SyncQueue`, `SyncStatus` | 4 |
| F12 Cloud sync | FR-019 (enhanced) | P7 | `services/backup_service.py` | — | 3 |
| F13 Version history | NEW-FR-029 | P3 | `routers/revisions.py`, `services/revision_service.py`, `schemas/revision.py`, `models/revision.py` | `EntryRevision` | 5 |
| F14 OCR | NEW-FR-030 | P2 | `services/ocr_service.py` | `OCRResult` | 2 |
| F15 Voice-to-text | FR-018 (existing) | P2 | `services/recording_service.py` | — | — |
| F16 Plugin architecture | NEW-FR-031 | P7 | `routers/plugins.py`, `services/plugin_service.py`, `core/hooks.py`, `models/plugin.py`, `schemas/plugin.py` | `Plugin`, `PluginHook` | 7 |
| F17 Full-text search | FR-004 (enhanced) | P5 | `services/entry_service.py` | `entries_fts` (virtual) | — |
| F18 Export (PDF/HTML) | NEW-FR-032 | P6 | `services/export_service.py` | — | 2 |
| F19 Automated backups | FR-023 (enhanced) | P6 | `services/backup_service.py` | — | 2 |
| F20 Hierarchical tags | FR-008, FR-009 | Done | — | — | — |
| F21 Analytics | NEW-FR-033 | P5 | `routers/analytics.py`, `services/analytics_service.py`, `schemas/analytics.py` | — | 7 |
| F22 Reminders | NEW-FR-034 | P6 | `routers/reminders.py`, `services/reminder_service.py`, `models/reminder.py`, `schemas/reminder.py` | `Reminder` | 5 |

---

## Appendix A — Final File Structure

```
backend/app/
├── main.py                          # Updated: Diarilinux branding, static files, all routers
├── core/
│   ├── __init__.py
│   ├── config.py                    # Updated: Ollama, Whisper, OCR, backup, app name
│   ├── database.py
│   ├── exceptions.py                # Updated: new exception types
│   ├── hooks.py                     # NEW: Plugin hook system (P7)
│   └── security.py                  # Extended: content encryption (P3)
├── routers/
│   ├── __init__.py
│   ├── ai.py                        # NEW (P2): Ollama grammar/rewrite
│   ├── analytics.py                 # NEW (P5): Statistics endpoints
│   ├── backup.py                    # Updated (P6): health check, scheduler reload
│   ├── encryption.py                # NEW (P3): Entry/selection encryption
│   ├── entries.py                   # Updated (P4): geotagging, map, nearby
│   ├── media.py                     # Updated (P2/P4): OCR, batch upload
│   ├── plugins.py                   # NEW (P7): Plugin management
│   ├── recordings.py                # Updated (P2): Whisper transcription
│   ├── reminders.py                 # NEW (P6): Writing reminders
│   ├── revisions.py                 # NEW (P3): Version history
│   ├── search.py                    # NEW (P5): Global search
│   ├── sync.py                      # NEW (P7): Offline sync queue
│   ├── tags.py
│   └── prompts.py
├── models/
│   ├── __init__.py                  # Updated: export new models
│   ├── backup.py
│   ├── entry.py                     # Updated (P3/P4): encryption + geotagging fields
│   ├── media.py                     # Updated (P4): is_inline field
│   ├── ocr_result.py                # NEW (P2): OCR cache
│   ├── plugin.py                    # NEW (P7): Plugin + PluginHook
│   ├── prompt.py
│   ├── recording.py
│   ├── reminder.py                  # NEW (P6): Writing reminders
│   ├── revision.py                  # NEW (P3): Entry revisions
│   ├── sync.py                      # NEW (P7): SyncQueue + SyncStatus
│   ├── tag.py
│   └── video_note.py                # NEW (P4): Video notes
├── schemas/
│   ├── __init__.py
│   ├── ai.py                        # NEW (P2)
│   ├── analytics.py                 # NEW (P5)
│   ├── backup.py
│   ├── encryption.py                # NEW (P3)
│   ├── entry.py                     # Updated (P4): geotagging fields
│   ├── media.py                     # Updated (P4): batch, inline
│   ├── ocr.py                       # NEW (P2)
│   ├── plugin.py                    # NEW (P7)
│   ├── recording.py
│   ├── reminder.py                  # NEW (P6)
│   ├── revision.py                  # NEW (P3)
│   ├── search.py                    # NEW (P5)
│   ├── sync.py                      # NEW (P7)
│   ├── tag.py
│   └── prompt.py
└── services/
    ├── __init__.py
    ├── analytics_service.py         # NEW (P5)
    ├── backup_service.py            # Updated (P6): scheduling, encryption
    ├── encryption_service.py        # NEW (P3)
    ├── entry_service.py             # Updated (P3/P4): revision hooks, geotagging
    ├── export_service.py            # NEW (P6)
    ├── media_service.py             # Updated (P4): batch, video
    ├── ocr_service.py               # NEW (P2)
    ├── ollama_service.py            # NEW (P2)
    ├── plugin_service.py            # NEW (P7)
    ├── prompt_service.py
    ├── recording_service.py         # Updated (P2): Whisper integration
    ├── reminder_service.py          # NEW (P6)
    ├── revision_service.py          # NEW (P3)
    ├── search_service.py            # NEW (P5)
    ├── sync_service.py              # NEW (P7)
    ├── tag_service.py
    └── video_service.py             # NEW (P4)
```

---

## Appendix B — Per-Phase Implementation Order

Within each phase, implement in this strict order:

1. **Models + Alembic Migrations** — Database schema first
2. **Schemas** — Pydantic validation
3. **Services** — Business logic (testable in isolation)
4. **Routers** — HTTP endpoints
5. **Tests** — Unit tests for services, integration tests for routers
6. **Documentation** — Update SPEC.md, DESIGN.md, ADRs

This ensures each feature is database-ready, validated, and testable before the HTTP layer is added.
