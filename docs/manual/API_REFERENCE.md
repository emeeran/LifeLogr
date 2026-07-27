# LifeLogr — API Reference

> REST API documentation for the LifeLogr backend (FastAPI).

Base URL: `http://localhost:8000/api/v1`

> In the **web** build the launcher picks a free local port (it prefers **18765** so
> that OAuth sign-in callbacks complete on the loopback interface) and falls back to
> `8000`–`8019`. The backend always binds to `127.0.0.1` (loopback only).

---

## Table of Contents

1. [Authentication & Limits](#authentication--limits)
2. [Entries](#entries)
3. [Notes](#notes)
4. [Tags](#tags)
5. [Templates](#templates)
6. [Media](#media)
7. [Recordings](#recordings)
8. [Video Notes](#video-notes)
9. [Search](#search)
10. [AI](#ai)
11. [AI Providers](#ai-providers)
12. [TTS](#tts)
13. [Prompts](#prompts)
14. [Encryption](#encryption)
15. [Reminders](#reminders)
16. [Export](#export)
17. [Backup & Cloud Providers](#backup--cloud-providers)
18. [Sync](#sync)
19. [System](#system)
20. [Memorial](#memorial)
21. [Settings](#settings)
22. [Error Responses](#error-responses)

---

## Authentication & Limits

LifeLogr runs locally as a **single-user** app and binds to `127.0.0.1` only — there
is **no authentication**. Behind a reverse proxy / shared deployment, add auth at the
proxy layer.

**Rate limiting:** 60 requests/minute per IP, **scoped to production deployments
only** (`APP_ENV=production`) — the desktop app does not self-throttle its background
enrichment.

---

## Entries

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/entries` | Create a journal entry |
| `GET` | `/entries` | List entries (paginated, filterable) |
| `GET` | `/entries/calendar/{year}/{month}` | All entries for a calendar month |
| `GET` | `/entries/search` | Legacy entry search (prefer `/search`) |
| `GET` | `/entries/{entry_id}` | Get a single entry |
| `PATCH` | `/entries/{entry_id}` | Update an entry |
| `DELETE` | `/entries/{entry_id}` | Soft-delete an entry |
| `POST` | `/entries/{entry_id}/restore` | Restore a soft-deleted entry (re-indexes FTS) |
| `POST` | `/entries/reset` | **Irreversible** — delete all entries, tags, media, recordings |
| `POST` | `/entries/import` | Import entries from a JSON payload |
| `POST` | `/entries/import/file` | Import from an uploaded file (`.diary` / `.json` / `.zip`) |
| `POST` | `/entries/deduplicate` | Find & soft-delete duplicates (by date + title) |
| `GET` | `/entries/export/markdown` | Export as Markdown ZIP |
| `GET` | `/entries/export/diarium` | Export as Diarium JSON |
| `GET` | `/entries/export/json` | Export as JSON |
| `GET` | `/entries/export/diarium-db` | Export as a Diarium SQLite database |

### Create Entry
```
POST /entries
```
```json
{ "entry_date": "2026-05-19", "title": "My Day", "body": "Content…", "tag_ids": [1, 3] }
```
**Response:** `201` → `EntryResponse`. Body is capped at 1,000,000 characters.

### List Entries
```
GET /entries?offset=0&limit=50&tag_ids=1&tag_ids=2&year=2026&month=5
```
Returns `EntryListResponse` (`items`, `total`, `offset`, `limit`). Each item includes
`tags`, `media_count`, `has_recording`, and `is_encrypted`.

### Import from file
```
POST /entries/import/file     (multipart/form-data, field: file)
```
Supports Diarium `.diary` (SQLite), `.json`, and Markdown `.zip` archives.
**Response:** `{ "imported": 15, "skipped": 2 }`

### Deduplicate
```
POST /entries/deduplicate
```
**Response:** `{ "groups_found": 3, "duplicates_removed": 3 }`

---

## Notes

Notes are standalone documents organized into **folders**, each with tabbed **pages**
and its own **media**.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/notes` | Create a note |
| `GET` | `/notes` | List notes (paginated) |
| `GET` | `/notes/search` | Full-text search notes |
| `POST` | `/notes/web-clip` | Clip a URL's text into a note (SSRF-hardened) |
| `GET` | `/notes/{note_id}` | Get a note (with pages) |
| `PATCH` | `/notes/{note_id}` | Update a note |
| `POST` | `/notes/folders` · `GET` · `PATCH /{id}` · `DELETE /{id}` | Folder CRUD |
| `POST` | `/notes/{note_id}/pages` | Add a page |
| `PATCH` | `/notes/{note_id}/pages/{page_id}` | Update a page |
| `DELETE` | `/notes/{note_id}/pages/{page_id}` | Delete a page |
| `POST` | `/notes/{note_id}/pages/reorder` | Reorder pages |
| `POST` | `/notes/{note_id}/media` | Attach media (upload) |
| `POST` | `/notes/{note_id}/media/from-path` | Attach media from a local file path (desktop) |
| `GET` | `/notes/{note_id}/media` | List a note's media |
| `GET` | `/notes/{note_id}/media/{media_id}/file` | Download a note media file |
| `DELETE` | `/notes/{note_id}/media/{media_id}` | Delete note media |
| `POST` | `/notes/{note_id}/media/{media_id}/ocr` | OCR a note image |

### Web-clip
```
POST /notes/web-clip        { "url": "https://example.com/article", "note_id": 12 }
```
Fetches the page **server-side** through an SSRF-hardened extractor (internal /
loopback addresses blocked on every hop, including redirects) and returns markdown.

---

## Tags

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/tags` | Create a tag (optional `parent_id` for hierarchy) |
| `GET` | `/tags` | List tags |
| `GET` | `/tags/tree` | Hierarchical tree with `children` |
| `GET` | `/tags/{tag_id}` | Get a tag |
| `PATCH` | `/tags/{tag_id}` | Rename a tag |
| `DELETE` | `/tags/{tag_id}` | Delete a tag |

Tags are **shared** across entries and notes.

---

## Templates

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/templates` | List templates (built-in + custom) |
| `POST` | `/templates` | Create a custom template |
| `PATCH` | `/templates/{template_id}` | Update (custom only) |
| `DELETE` | `/templates/{template_id}` | Delete (custom only) |

```json
{ "name": "My Template", "body": "## Section 1\n\n## Section 2\n" }
```

---

## Media

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/media` | Upload a media file (max 25 MB) |
| `POST` | `/media/batch` | Upload multiple files |
| `GET` | `/media/all` | Media timeline (gallery) |
| `GET` | `/media/entry/{entry_id}` | List media for an entry |
| `GET` | `/media/{media_id}` | Media metadata |
| `GET` | `/media/{media_id}/file` | Download the binary |
| `POST` | `/media/{media_id}/ocr` | OCR an image (`?language=eng`) |
| `DELETE` | `/media/{media_id}` | Delete media (cleans up the file) |

### Upload
```
POST /media        (multipart/form-data: file, entry_id, caption?)
```
**Response:** `MediaResponse` (`id`, `entry_id`, `filename`, `media_type`,
`file_size`, `caption`, …).

### OCR
```
POST /media/{media_id}/ocr?language=eng
```
**Response:** `{ "media_id": 1, "extracted_text": "…", "confidence": 0.92, "language": "eng" }`

> Images are stored as WebP; OCR runs locally via **Tesseract** (never leaves the
> device). Returns a helpful error if Tesseract is missing.

---

## Recordings

Voice clips attached to entries.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/recordings` | Upload a recording (`file` + `entry_id`) |
| `POST` | `/recordings/start` | Start a backend-driven recording |
| `POST` | `/recordings/stop` | Stop and persist the recording |
| `GET` | `/recordings/entry/{entry_id}` | List recordings for an entry |
| `GET` | `/recordings/{recording_id}` | Get recording metadata |
| `DELETE` | `/recordings/{recording_id}` | Delete a recording |

**Response (`VoiceRecordingResponse`):** includes `duration_seconds`,
`audio_format`, and `media_id` (the recording is stored as media).

> **Speech-to-text transcription is not available** in this release. Recordings are
> stored as audio attachments only.

---

## Video Notes

Short video clips attached to entries.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/videos` | Upload a video note |
| `GET` | `/videos/entry/{entry_id}` | List videos for an entry |
| `GET` | `/videos/{video_id}` | Video metadata |
| `GET` | `/videos/{video_id}/file` | Download the video file |
| `DELETE` | `/videos/{video_id}` | Delete a video note |

---

## Search

### Global Search
```
GET /search?q={query}&mode=hybrid&tag_ids=1,2&date_from=2026-01-01&date_to=2026-12-31&offset=0&limit=20
```

| Param | Type | Default | Description |
|---|---|---|---|
| `q` | string | — | **Required.** Query |
| `mode` | string | `hybrid` | `keyword` · `semantic` · `hybrid` |
| `tag_ids` | string | — | Comma-separated tag IDs |
| `date_from` / `date_to` | string | — | `YYYY-MM-DD` |
| `offset` / `limit` | int | `0` / `20` | Pagination |

| Mode | Description |
|---|---|
| `keyword` | SQLite FTS5 full-text, BM25-ranked |
| `semantic` | Meaning-based via `nomic-embed-text` embeddings |
| `hybrid` | Keyword + semantic via Reciprocal Rank Fusion |

**Response:** `GlobalSearchResponse` — `items` (each with `snippet` of highlighted
match, `rank`, and `similarity_score`), `total`, `offset`, `limit`. Results span
entries **and** notes.

> Semantic / hybrid modes require the embedding model and enriched entries. If a cloud
> AI provider is active, embeddings are generated through it.

---

## AI

AI runs **locally via Ollama by default** and can optionally route through a cloud
provider (see [AI Providers](#ai-providers)). When a cloud provider is active, these
endpoints call it; otherwise they call local Ollama. Ollama is the automatic fallback
if the cloud provider is unreachable.

### Status & models
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ai/status` | Service status (Ollama availability, model, embed model) |
| `POST` | `/ai/pull-model?model=…` | Trigger a background Ollama model pull |

### On-demand text tools
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ai/grammar-check` | Grammar check |
| `POST` | `/ai/spell-check` | Spell check |
| `POST` | `/ai/rewrite` | Rewrite (style/instructions) |
| `POST` | `/ai/rewrite-for-clarity` | Rewrite for clarity |
| `POST` | `/ai/change-tone` | Change tone |
| `POST` | `/ai/change-voice` | Active ↔ passive voice |
| `POST` | `/ai/expand` | Expand text |
| `POST` | `/ai/define-text` | Define terms |
| `POST` | `/ai/analyze-text` | Emotions/themes/summary of text |
| `POST` | `/ai/suggest-tags` | Suggest tags for content |
| `POST` | `/ai/continue-writing` | Writer's-block continuation |
| `POST` | `/ai/tool/{tool_id}` | **Generic registry tool** (see below) |

#### Generic tool (`POST /ai/tool/{tool_id}`)
Registry-driven tools — `result` returned as plain text:

| `tool_id` | Output |
|---|---|
| `summarize` | 2–3 sentence summary |
| `key-points` | 3–7 markdown bullets |
| `action-items` | markdown checklist of to-dos |
| `shorten` | condensed (~half length) |
| `simplify` | plain-language / ELI5 rewrite |
| `polish` | improved word choice & flow |
| `translate` | translation into `param` language (default `Spanish`) |
| `add-structure` | reorganized with headings/bullets |
| `title` | concise (≤8 words) title |

**Body:** `{ "text": "…", "param": "French" }` (`param` optional, validated against
the tool's allowed values). **Response:** `{ "result": "…" }`.
Errors: `404` unknown tool · `400` invalid `param` · `422` empty `text`.

### Insights (background-generated, read here)
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ai/themes` | Recurring themes across entries |
| `GET` | `/ai/entry-analysis/{entry_id}` | Sentiment + summary + reflection prompts for an entry |
| `GET` | `/ai/similar/{entry_id}?top_k=5` | Entries with similar embeddings |
| `GET` | `/ai/on-this-day` | Past-years entries for today + an AI reflection |
| `GET` | `/ai/digests?limit=10` | List weekly digests |
| `GET` | `/ai/digests/latest` | Most recent weekly digest |
| `POST` | `/ai/digests/generate` | Generate a weekly digest (map-reduce over entry summaries) |

> Background analysis (summary, sentiment, reflection prompts, tag suggestions,
> embeddings) runs automatically after you save an entry, controlled by the per-feature
> toggles in **Settings → AI**.

---

## AI Providers

Manage optional cloud providers. All cloud presets speak the OpenAI chat-completions
API: **OpenAI, Groq, OpenRouter, Kimi (Moonshot), Google Gemini**, plus a **Custom**
endpoint. API keys are AES-GCM encrypted at rest and **never returned** by the API.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ai/providers/presets` | Catalogue of provider presets (label, base URL, defaults) |
| `GET` | `/ai/providers` | List configured providers |
| `POST` | `/ai/providers` | Add a provider (`name`, `preset`, `base_url`, `model`, `api_key?`) |
| `PATCH` | `/ai/providers/{provider_id}` | Update a provider |
| `DELETE` | `/ai/providers/{provider_id}` | Delete a provider |
| `POST` | `/ai/providers/{provider_id}/activate` | Set as the active provider |
| `POST` | `/ai/providers/{provider_id}/test` | Probe the endpoint (1-token completion) |
| `GET` | `/ai/providers/{provider_id}/models` | List models the endpoint exposes (`GET /models`) |
| `POST` | `/ai/providers/models` | Preview models for a not-yet-saved provider config |

**Precedence:** the active provider is used; if none is active (or it's the `ollama`
preset), local Ollama is used. See [Privacy & Data Egress](#system) for what this
means for data leaving the device.

---

## TTS

Read-aloud via Microsoft Edge TTS, cached on disk.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/tts/voices` | List available voices |
| `GET` | `/tts/entry/{entry_id}?voice=…` | Speak an entry |
| `POST` | `/tts/speak` | Speak arbitrary text |
| `GET` | `/tts/file/{key}` | Fetch a cached TTS audio file (Range-capable) |
| `POST` | `/tts/prewarm` | Background-cache TTS for an entry |

**Body (`/tts/speak`):** `{ "text": "…", "voice": "en-US-AvaNeural" }`
**Response:** audio blob.

---

## Prompts

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/prompts/today` | Today's writing prompt |

---

## Encryption

AES-256-GCM with a scrypt-derived key (per-item salt).

### Entry encryption
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/entries/{entry_id}/encryption/encrypt` | Encrypt an entry |
| `POST` | `/entries/{entry_id}/encryption/decrypt` | Decrypt an entry |
| `GET` | `/entries/{entry_id}/encryption/status` | Encryption status |

### Note encryption
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/notes/{note_id}/encryption/encrypt` | Encrypt a note |
| `POST` | `/notes/{note_id}/encryption/decrypt` | Decrypt a note |
| `GET` | `/notes/{note_id}/encryption/status` | Encryption status |

**Body:** `{ "passphrase": "…" }`

---

## Reminders

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/reminders` | Create a reminder |
| `GET` | `/reminders` | List reminders |
| `GET` | `/reminders/{reminder_id}` | Get a reminder |
| `PATCH` | `/reminders/{reminder_id}` | Update a reminder |
| `DELETE` | `/reminders/{reminder_id}` | Delete a reminder |
| `POST` | `/reminders/{reminder_id}/test` | Fire a test notification |

```json
{
  "title": "Evening Journal",
  "message": "Time to write your evening reflection!",
  "reminder_time": "21:00",
  "days_of_week": "0,1,2,3,4,5,6",
  "is_active": true
}
```

Reminders are APScheduler-driven and reconciled with the DB on startup and after every
CRUD op; missed reminders are caught up on launch.

---

## Export

Whole-journal document exports (in addition to the per-format entry exports under
`/entries/export/*`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/export/html?start_date=…&end_date=…` | Styled single HTML document |
| `GET` | `/export/pdf?start_date=…&end_date=…` | PDF (desktop — bundled fpdf2) |
| `GET` | `/export/markdown` | Obsidian-compatible Markdown ZIP |

> Exports never include encrypted content in cleartext.

---

## Backup & Cloud Providers

### Local backup & schedule
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/backup/export` | Download a full `.tar.gz` (DB + media) |
| `POST` | `/backup/import` | Restore from an uploaded `.tar.gz` (path-traversal-safe, atomic) |
| `POST` | `/backup/schedule` | Schedule an automated backup (cron) |
| `GET` | `/backup/schedule/status` | Current schedule |
| `DELETE` | `/backup/schedule` | Remove the schedule |

### Config & cloud run
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/backup/config` | Create a backup config (provider + credentials + cron) |
| `GET` | `/backup/config` | List backup configs |
| `DELETE` | `/backup/config/{config_id}` | Delete a config |
| `POST` | `/backup/config/{config_id}/test` | Test a cloud connection |
| `POST` | `/backup/config/migrate-credentials` | Upgrade legacy v1 credentials → v2 (HKDF) |
| `POST` | `/backup/run` | Incremental backup to the configured provider |
| `POST` | `/backup/run-now` | Run a backup immediately (local or cloud) |
| `GET` | `/backup/snapshots` | Paginated backup history |
| `DELETE` | `/backup/snapshots/{snapshot_id}` | Delete a snapshot (+ cloud file) |
| `POST` | `/backup/restore` | Restore from the latest cloud backup |

### OAuth cloud providers
Each provider exposes the same pair; the callback is served on the loopback
`127.0.0.1:18765` so the sign-in round-trips locally. Tokens are encrypted at rest and
auto-refreshed.

| Method | Path | Provider |
|---|---|---|
| `GET` | `/backup/google-drive/auth-url` · `/callback` | Google Drive (`drive.file`, `drive.appdata`) |
| `GET` | `/backup/onedrive/auth-url` · `/callback` | OneDrive (`Files.ReadWrite.AppFolder offline_access`) |
| `GET` | `/backup/dropbox/auth-url` · `/callback` | Dropbox (`token_access_type=offline`) |
| `GET` | `/backup/box/auth-url` · `/callback` | Box (rotating refresh tokens) |

**WebDAV / Synology NAS** are configured via `POST /backup/config` with
`provider: "webdav"` (Synology is stored as `webdav`).

---

## Sync

An operation queue plus cloud push/pull (last-writer-wins on `updated_at`).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sync/enqueue` | Queue an operation for later sync |
| `GET` | `/sync/pending` | List unsynced operations |
| `GET` | `/sync/status` | Sync status per provider |
| `POST` | `/sync/flush` | Mark pending operations as synced |
| `POST` | `/sync/cloud/push` | Push pending changes to the cloud (optional E2E encryption) |
| `POST` | `/sync/cloud/pull` | Pull & merge remote changes |

---

## System

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/system/integrity` | Cached integrity report |
| `POST` | `/system/integrity` | Re-run integrity checks |
| `POST` | `/system/integrity/rebuild-search-index` | Rebuild the FTS5 search index |
| `GET` | `/system/egress-report` | **Privacy egress report** (see below) |

### Egress report
`GET /system/egress-report` returns a per-surface table of what leaves the device:

| Surface | `leaves_device` |
|---|---|
| Cloud AI tools & analysis | `true` only when a non-Ollama provider is active |
| Embeddings | mirrors the AI provider |
| Cloud backup | `true` only for configured providers |
| Web-clip | `false` (only the URL leaves; content stays local) |
| OCR | `false` (local Tesseract) |

The **Settings → Privacy** tab renders this report live.

---

## Memorial

Background audio for the dedication/memorial tribute (played via a system audio player
to bypass browser autoplay restrictions).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/memorial/audio/start` | Start the memorial audio player |
| `POST` | `/memorial/audio/stop` | Stop the memorial audio player |

---

## Settings

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/settings` | Get application settings |
| `PUT` | `/settings` | Update application settings |
| `GET` | `/settings/models` | List available AI models |
| `GET` | `/settings/storage-path` | Storage path info |
| `POST` | `/settings/storage-path` | Relocate the data directory |
| `POST` | `/settings/vacuum` | Vacuum the database |
| `POST` | `/settings/integrity-check` | Run an integrity check |

`GET /settings` is the API-consumer source of truth for the app version (`APP_VERSION`).
The in-app **About** version is injected at frontend build time (`VITE_APP_VERSION`),
so it always matches the installed bundle.

---

## Error Responses

All errors use:
```json
{ "detail": "Error message describing what went wrong" }
```

| Code | Meaning |
|---|---|
| `200` | Success |
| `201` | Created |
| `204` | No Content (successful deletion) |
| `400` | Bad Request (invalid input) |
| `404` | Not Found |
| `409` | Conflict |
| `413` | Payload Too Large (media exceeds 25 MB) |
| `422` | Validation Error (Pydantic) |
| `429` | Too Many Requests (rate limited, production only) |
| `500` | Internal Server Error |
| `501` | Not Implemented (missing optional dependency) |

### Validation errors (422)
```json
{
  "detail": [
    { "loc": ["body", "entry_date"], "msg": "field required", "type": "missing" }
  ]
}
```

### Interactive docs
In development, interactive API docs are available at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

> These are disabled in production (`APP_ENV=production`).
