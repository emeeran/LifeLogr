# DailyByte — API Reference

> REST API documentation for the DailyByte backend (FastAPI).

Base URL: `http://localhost:8000/api/v1`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Entries](#entries)
3. [Tags](#tags)
4. [Templates](#templates)
5. [Media](#media)
6. [Recordings](#recordings)
7. [Search](#search)
8. [Analytics](#analytics)
9. [AI](#ai)
10. [Export](#export)
11. [Backup](#backup)
12. [Sync](#sync)
13. [Encryption](#encryption)
14. [Revisions](#revisions)
15. [Geotagging](#geotagging)
16. [Reminders](#reminders)
17. [TTS](#tts)
18. [Plugins](#plugins)
19. [Error Responses](#error-responses)

---

## Authentication

Currently, DailyByte runs locally without authentication. In production deployments behind a reverse proxy, add authentication at the proxy layer.

**Rate Limiting:** 60 requests per minute per IP (in-memory).

---

## Entries

### List Entries

```
GET /entries
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 50 | Results per page |
| `tag_ids` | int[] | — | Filter by tag IDs (repeat param) |
| `year` | int | — | Filter by year |
| `month` | int | — | Filter by month (1-12) |

**Response:** `EntryListResponse`

```json
{
  "items": [
    {
      "id": 1,
      "entry_date": "2026-05-19",
      "title": "My Day",
      "body": "Today was productive...",
      "is_deleted": false,
      "is_encrypted": false,
      "tags": [{"id": 1, "name": "personal"}],
      "media_count": 2,
      "has_recording": false,
      "created_at": "2026-05-19T10:00:00",
      "updated_at": "2026-05-19T10:30:00"
    }
  ],
  "total": 42,
  "offset": 0,
  "limit": 50
}
```

### Get Entry

```
GET /entries/{entry_id}
```

**Response:** `EntryResponse` (single object)

### Create Entry

```
POST /entries
```

**Body:** `EntryCreate`

```json
{
  "entry_date": "2026-05-19",
  "title": "My Day",
  "body": "Content here...",
  "tag_ids": [1, 3]
}
```

**Response:** `201 Created` → `EntryResponse`

### Update Entry

```
PATCH /entries/{entry_id}
```

**Body:** `EntryUpdate`

```json
{
  "title": "Updated Title",
  "body": "Updated content...",
  "tag_ids": [1, 2, 3]
}
```

**Response:** `EntryResponse`

### Delete Entry

```
DELETE /entries/{entry_id}
```

Soft-deletes the entry (`is_deleted = true`).

**Response:** `204 No Content`

### Calendar Month

```
GET /entries/calendar/{year}/{month}
```

Returns all entries for the specified month.

**Response:** `EntryResponse[]`

### Search Entries

```
GET /entries/search?q={query}&offset=0&limit=20
```

Uses SQLite FTS5 full-text search.

**Response:** `EntryListResponse`

### Import Entries

```
POST /entries/import
```

**Body:**

```json
[
  {"entry_date": "2026-01-01", "title": "New Year", "body": "Happy new year!"}
]
```

**Response:**

```json
{"imported": 1, "skipped": 0}
```

### Import from File

```
POST /entries/import/file
```

**Body:** `multipart/form-data` with `file` field

Supports: `.diary` (Diarium), `.json`, `.zip` (Markdown archive)

**Response:**

```json
{"imported": 15, "skipped": 2}
```

### Export Markdown

```
GET /entries/export/markdown?start_date=2026-01-01&end_date=2026-12-31
```

**Response:** ZIP file download (Diarium-compatible format)

### Deduplicate

```
POST /entries/deduplicate
```

Finds and soft-deletes duplicate entries based on date + title.

**Response:**

```json
{"groups_found": 3, "duplicates_removed": 3}
```

### Reset Database

```
POST /entries/reset
```

Deletes all entries, tags, media, and recordings. **Irreversible.**

**Response:**

```json
{"status": "ok", "message": "All data deleted"}
```

---

## Tags

### List Tags

```
GET /tags
```

**Response:** `TagResponse[]`

### Tag Tree

```
GET /tags/tree
```

Returns tags in hierarchical tree structure with children.

**Response:** `TagResponse[]` with nested `children`

### Get Tag

```
GET /tags/{tag_id}
```

**Response:** `TagResponse`

### Create Tag

```
POST /tags
```

**Body:**

```json
{"name": "Travel", "parent_id": null}
```

**Response:** `201 Created` → `TagResponse`

### Update Tag

```
PATCH /tags/{tag_id}
```

**Body:**

```json
{"name": "Renamed Tag"}
```

**Response:** `TagResponse`

### Delete Tag

```
DELETE /tags/{tag_id}
```

**Response:** `204 No Content`

---

## Templates

### List Templates

```
GET /templates
```

**Response:** `TemplateResponse[]`

```json
[
  {
    "id": 1,
    "name": "Daily Reflection",
    "body": "## How I'm feeling\n\n...",
    "is_builtin": true,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00"
  }
]
```

### Create Template

```
POST /templates
```

**Body:**

```json
{"name": "My Template", "body": "## Section 1\n\n## Section 2\n"}
```

**Response:** `201 Created` → `TemplateResponse`

### Update Template

```
PATCH /templates/{template_id}
```

Cannot update built-in templates (`is_builtin=true`).

**Body:**

```json
{"name": "Updated Name", "body": "New template body"}
```

**Response:** `TemplateResponse`

### Delete Template

```
DELETE /templates/{template_id}
```

Cannot delete built-in templates.

**Response:** `204 No Content`

---

## Media

### Upload Media

```
POST /media
```

**Body:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | The media file (max 25 MB) |
| `entry_id` | int | Yes | Target entry ID |
| `caption` | string | No | Optional caption |

**Response:** `MediaResponse`

```json
{
  "id": 1,
  "entry_id": 5,
  "filename": "photo.jpg",
  "media_type": "image/jpeg",
  "file_size": 1048576,
  "caption": "Sunset photo",
  "created_at": "2026-05-19T10:00:00"
}
```

### Get Media

```
GET /media/{media_id}
```

**Response:** `MediaResponse`

### Download Media File

```
GET /media/{media_id}/file
```

**Response:** Binary file with appropriate Content-Type header

### Delete Media

```
DELETE /media/{media_id}
```

**Response:** `204 No Content`

### OCR (Extract Text from Image)

```
POST /media/{media_id}/ocr?language=eng
```

**Response:**

```json
{
  "media_id": 1,
  "extracted_text": "Extracted text content...",
  "confidence": 0.92,
  "language": "eng"
}
```

### Batch Upload

```
POST /media/batch
```

**Body:** `multipart/form-data` with multiple `files` fields + `entry_id`

### List Media by Entry

```
GET /media/entry/{entry_id}
```

**Response:** `MediaResponse[]`

---

## Recordings

### Upload Recording

```
POST /recordings
```

**Body:** `multipart/form-data` with `file` and `entry_id`

**Response:** `VoiceRecordingResponse`

```json
{
  "id": 1,
  "entry_id": 5,
  "media_id": 10,
  "duration_seconds": 120,
  "audio_format": "webm",
  "transcription": null,
  "is_transcribed": false,
  "created_at": "2026-05-19T10:00:00"
}
```

### List Recordings by Entry

```
GET /recordings/entry/{entry_id}
```

**Response:** `VoiceRecordingResponse[]`

### Transcribe Recording

```
POST /recordings/{recording_id}/transcribe
```

Uses local Whisper model for transcription.

**Response:** `VoiceRecordingResponse` (with `transcription` populated)

### Get Recording

```
GET /recordings/{recording_id}
```

### Delete Recording

```
DELETE /recordings/{recording_id}
```

---

## Search

### Global Search

```
GET /search?q={query}&mode=hybrid&tag_ids=1,2&date_from=2026-01-01&date_to=2026-12-31&offset=0&limit=20
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | — | **Required.** Search query |
| `mode` | string | `hybrid` | Search mode: `keyword`, `semantic`, or `hybrid` |
| `tag_ids` | string | — | Comma-separated tag IDs |
| `date_from` | string | — | Start date (YYYY-MM-DD) |
| `date_to` | string | — | End date (YYYY-MM-DD) |
| `offset` | int | `0` | Pagination offset |
| `limit` | int | `20` | Results per page |

**Search Modes:**

| Mode | Description |
|------|-------------|
| `keyword` | Traditional FTS5 full-text search with BM25 ranking |
| `semantic` | AI-powered meaning-based search using `nomic-embed-text` embeddings |
| `hybrid` | Combines keyword and semantic results via Reciprocal Rank Fusion (default) |

> Semantic and hybrid modes require the `nomic-embed-text` embedding model to be pulled and entries to have been enriched (happens automatically after save).

**Response:** `GlobalSearchResponse`

```json
{
  "items": [
    {
      "id": 5,
      "entry_date": "2026-05-19",
      "title": "My Day",
      "snippet": "...text with <mark>highlighted</mark> match...",
      "rank": -3.2,
      "similarity_score": 0.87
    }
  ],
  "total": 7,
  "offset": 0,
  "limit": 20
}
```

---

## Analytics

### Overview

```
GET /analytics/overview
```

```json
{
  "total_entries": 142,
  "total_words": 52840,
  "total_media": 38,
  "total_recordings": 5,
  "date_range_start": "2025-06-01",
  "date_range_end": "2026-05-19",
  "longest_streak": 14,
  "current_streak": 3
}
```

### Writing Habits

```
GET /analytics/habits
```

Returns entry count grouped by day of week.

### Word Count

```
GET /analytics/words
```

```json
{
  "total_words": 52840,
  "average_words_per_entry": 372,
  "longest_entry_words": 2840,
  "shortest_entry_words": 12
}
```

### Tag Statistics

```
GET /analytics/tags
```

Returns usage count per tag.

### Mood Distribution

```
GET /analytics/moods
```

Returns mood distribution across entries.

### Sentiment Timeline

```
GET /analytics/sentiment-timeline?year=2026&month=5
```

Returns valence scores over time for AI-analyzed entries within the specified month.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `year` | int | Year (required) |
| `month` | int | Month 1-12 (required) |

**Response:**

```json
[
  {
    "entry_date": "2026-05-01",
    "valence": 0.6,
    "primary_emotion": "happy",
    "intensity": 7
  },
  {
    "entry_date": "2026-05-03",
    "valence": -0.3,
    "primary_emotion": "anxious",
    "intensity": 5
  }
]
```

### Heatmap

```
GET /analytics/heatmap?year=2026
```

```json
{
  "year": 2026,
  "days": [
    {"date": "2026-01-01", "count": 2},
    {"date": "2026-01-02", "count": 0}
  ]
}
```

### Media Statistics

```
GET /analytics/media
```

```json
{
  "total_images": 30,
  "total_videos": 3,
  "total_recordings": 5,
  "total_size_bytes": 157286400
}
```

---

## AI

### Check AI Status

```
GET /ai/status
```

```json
{
  "ollama_available": true,
  "model_name": "llama3.2:3b",
  "model_loaded": true,
  "embed_model_available": true,
  "error": null
}
```

### Grammar Check

```
POST /ai/grammar-check
```

**Body:** `{"text": "Your journal entry text..."}`

**Response:**

```json
{
  "corrected_text": "Corrected version of the text...",
  "suggestions": [
    {
      "offset": 15,
      "length": 4,
      "original": "teh",
      "suggestion": "the",
      "rule_id": "GRAMMAR_001",
      "message": "Possible typo"
    }
  ]
}
```

### Spell Check

```
POST /ai/spell-check
```

**Body:** `{"text": "Text to check..."}`

**Response:** Same format as grammar check with misspellings.

### Rewrite

```
POST /ai/rewrite
```

**Body:**

```json
{
  "text": "Original text...",
  "style": "concise",
  "instructions": "Make it shorter while preserving meaning"
}
```

**Response:**

```json
{
  "rewritten_text": "Shortened version...",
  "style": "concise"
}
```

### Suggest Tags

```
POST /ai/suggest-tags
```

Suggests relevant tags for an entry based on its content. Considers existing tag names for reuse.

**Body:**

```json
{"text": "Had a great hiking trip in the mountains today..."}
```

**Response:**

```json
{
  "tags": ["travel", "nature", "exercise", "outdoors"]
}
```

### Get Entry Analysis

```
GET /ai/entry-analysis/{entry_id}
```

Returns the AI-generated analysis for an entry: sentiment, auto-summary, and reflection prompts.

**Response:**

```json
{
  "entry_id": 5,
  "sentiment": {
    "primary_emotion": "happy",
    "secondary_emotion": "grateful",
    "intensity": 7,
    "valence": 0.6
  },
  "summary": "A productive day spent hiking and reflecting on recent accomplishments.",
  "reflection_prompts": [
    "What made this hiking trip particularly meaningful?",
    "How can you carry this sense of accomplishment into next week?",
    "What are you most grateful for from today?"
  ]
}
```

### Find Similar Entries

```
GET /ai/similar/{entry_id}?top_k=5
```

Finds entries with similar content using embedding cosine similarity.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `top_k` | int | `5` | Number of similar entries to return |

**Response:**

```json
{
  "entry_id": 5,
  "similar": [
    {
      "entry_id": 12,
      "entry_date": "2026-04-15",
      "title": "Mountain Weekend",
      "similarity": 0.89
    },
    {
      "entry_id": 28,
      "entry_date": "2026-03-22",
      "title": "Trail Running",
      "similarity": 0.82
    }
  ]
}
```

### Continue Writing (Writer's Block Helper)

```
POST /ai/continue-writing
```

Generates a 1-3 sentence continuation of the provided text to help overcome writer's block.

**Body:**

```json
{"text": "Today I visited the old library downtown. The architecture was stunning, with tall ceilings and..." }
```

**Response:**

```json
{
  "continuation": "wrought-iron chandeliers casting warm light across rows of weathered bookshelves. I spent hours wandering the aisles, discovering titles I hadn't thought about in years."
}
```

### On This Day Reflection

```
GET /ai/on-this-day
```

Fetches entries from today's date in past years and generates an AI reflection on personal growth and change.

**Response:**

```json
{
  "entries": [
    {
      "id": 42,
      "entry_date": "2024-05-21",
      "title": "Starting a new chapter",
      "body": "Today I decided to change careers...",
      "years_ago": 2
    }
  ],
  "reflection": "Two years ago you were at a crossroads, uncertain about a career change. Looking at your entries since then, you've shown remarkable resilience and growth..."
}
```

### Detect Recurring Themes

```
GET /ai/themes
```

Analyzes all entries with AI summaries to detect recurring themes and patterns over time.

**Response:**

```json
{
  "themes": [
    {
      "theme": "Career Growth",
      "frequency": 12,
      "months_active": ["2026-01", "2026-03", "2026-05"],
      "description": "Regular entries about professional development, learning new skills, and workplace challenges."
    },
    {
      "theme": "Health & Fitness",
      "frequency": 8,
      "months_active": ["2026-02", "2026-04"],
      "description": "Entries about exercise routines, diet changes, and physical wellbeing goals."
    }
  ]
}
```

### List Digests

```
GET /ai/digests?limit=10
```

Lists generated weekly digests in reverse chronological order.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | `10` | Maximum digests to return |

**Response:** `DigestResponse[]`

### Get Latest Digest

```
GET /ai/digests/latest
```

Returns the most recently generated weekly digest.

**Response:** `DigestResponse`

```json
{
  "id": 3,
  "week_start": "2026-05-12",
  "week_end": "2026-05-18",
  "themes": ["productivity", "self-reflection", "nature"],
  "emotional_trajectory": "The week started with some anxiety about deadlines, shifted to satisfaction mid-week as tasks were completed, and ended on a peaceful note with a weekend hike.",
  "notable_moments": [
    "Completed a major project milestone on Wednesday",
    "Had a meaningful conversation with an old friend on Thursday",
    "Discovered a new hiking trail on Saturday"
  ],
  "summary_text": "This was a week of contrasts — intense focus during workdays gave way to restorative weekends in nature. Key themes were productivity and the importance of balancing ambition with self-care.",
  "created_at": "2026-05-19T02:00:00"
}
```

### Generate Digest

```
POST /ai/digests/generate
```

Generates a new weekly digest for the most recent complete week (or current week). Uses a map-reduce approach: individual entry summaries are concatenated and sent to the LLM for a coherent narrative.

**Response:** `DigestResponse` (same format as above)

### Pull Embedding Model

```
POST /ai/pull-model?model=nomic-embed-text
```

Triggers download of an Ollama model. The pull runs in the background — the endpoint returns immediately.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `model` | string | **Required.** Model name to pull (e.g., `nomic-embed-text`) |

**Response:**

```json
{
  "status": "pulling",
  "model": "nomic-embed-text"
}
```

---

## Export

### Export HTML

```
GET /export/html?start_date=2026-01-01&end_date=2026-12-31
```

**Response:** Styled HTML document (text/html)

### Export PDF

```
GET /export/pdf?start_date=2026-01-01&end_date=2026-12-31
```

**Response:** PDF document (application/pdf)

> Requires WeasyPrint. Desktop-only.

---

## Backup

### Create Backup Config

```
POST /backup/config
```

**Body:**

```json
{
  "provider": "webdav",
  "credentials": {
    "url": "https://cloud.example.com/dav",
    "username": "user",
    "password": "pass"
  },
  "schedule_cron": "0 2 * * *"
}
```

### List Backup Configs

```
GET /backup/config
```

### Test Connection

```
POST /backup/config/{config_id}/test
```

### Run Backup

```
POST /backup/run
```

### List Snapshots

```
GET /backup/snapshots
```

### Restore from Backup

```
POST /backup/restore
```

### Export Local Backup

```
GET /backup/export
```

**Response:** `.tar.gz` file download

### Import Local Backup

```
POST /backup/import
```

**Body:** `multipart/form-data` with backup file

### Schedule Automated Backup

```
POST /backup/schedule
```

**Body:**

```json
{
  "backup_path": "/path/to/backup.tar.gz",
  "cron": "0 2 * * *"
}
```

### Check Schedule Status

```
GET /backup/schedule/status
```

### Remove Schedule

```
DELETE /backup/schedule
```

---

## Sync

### Enqueue Operation

```
POST /sync/enqueue
```

### Get Pending Operations

```
GET /sync/pending
```

### Get Sync Status

```
GET /sync/status
```

### Mark as Synced

```
POST /sync/flush
```

### Push to Cloud

```
POST /sync/cloud/push
```

### Pull from Cloud

```
POST /sync/cloud/pull
```

---

## Encryption

### Encrypt Entry

```
POST /entries/{entry_id}/encryption/encrypt
```

**Body:**

```json
{"passphrase": "my-secret-passphrase"}
```

### Decrypt Entry

```
POST /entries/{entry_id}/encryption/decrypt
```

**Body:**

```json
{"passphrase": "my-secret-passphrase"}
```

### Check Encryption Status

```
GET /entries/{entry_id}/encryption/status
```

---

## Revisions

### List Revisions

```
GET /entries/{entry_id}/revisions?offset=0&limit=50
```

### Get Revision

```
GET /entries/{entry_id}/revisions/{revision_number}
```

### Diff Revisions

```
GET /entries/{entry_id}/revisions/{from_rev}/diff/{to_rev}
```

```json
{
  "from_revision": 1,
  "to_revision": 3,
  "title_changed": true,
  "body_changed": true,
  "from_title": "Old Title",
  "to_title": "New Title",
  "from_body": "Old body content",
  "to_body": "New body content"
}
```

### Restore Revision

```
POST /entries/{entry_id}/revisions/{revision_number}/restore
```

---

## Geotagging

### Set Geotag

```
PUT /entries/{entry_id}/geotag
```

**Body:**

```json
{
  "latitude": 51.5074,
  "longitude": -0.1278,
  "location_name": "London, UK"
}
```

### Remove Geotag

```
DELETE /entries/{entry_id}/geotag
```

### Map View

```
GET /entries/map
```

Returns all geotagged entries.

### Nearby Entries

```
GET /entries/nearby?lat=51.5074&lon=-0.1278&radius_km=10&limit=20
```

```json
{
  "items": [
    {
      "id": 5,
      "entry_date": "2026-05-19",
      "title": "London Visit",
      "latitude": 51.5080,
      "longitude": -0.1280,
      "location_name": "London, UK",
      "distance_km": 0.07
    }
  ],
  "total": 1
}
```

---

## Reminders

### Create Reminder

```
POST /reminders
```

**Body:**

```json
{
  "title": "Evening Journal",
  "message": "Time to write your evening reflection!",
  "reminder_time": "21:00",
  "days_of_week": "0,1,2,3,4,5,6",
  "is_active": true
}
```

### List Reminders

```
GET /reminders
```

### Update Reminder

```
PATCH /reminders/{reminder_id}
```

### Delete Reminder

```
DELETE /reminders/{reminder_id}
```

### Test Notification

```
POST /reminders/{reminder_id}/test
```

```json
{"sent": true, "title": "Evening Journal"}
```

---

## TTS

### List Voices

```
GET /tts/voices
```

### Speak Entry

```
GET /tts/entry/{entry_id}?voice=en-US-AvaNeural
```

**Response:** Audio blob

### Speak Text

```
POST /tts/speak
```

**Body:**

```json
{"text": "Text to speak", "voice": "en-US-AvaNeural"}
```

**Response:** Audio blob

---

## Plugins

### Install Plugin

```
POST /plugins
```

**Body:**

```json
{
  "name": "word-cloud",
  "version": "1.0.0",
  "description": "Generate word clouds from entries",
  "entry_point": "word_cloud.main"
}
```

### List Plugins

```
GET /plugins
```

### Get Plugin

```
GET /plugins/{plugin_id}
```

### Enable Plugin

```
POST /plugins/{plugin_id}/enable
```

### Disable Plugin

```
POST /plugins/{plugin_id}/disable
```

### Uninstall Plugin

```
DELETE /plugins/{plugin_id}
```

### Get Plugin Hooks

```
GET /plugins/{plugin_id}/hooks
```

### List Hook Registry

```
GET /plugins/hooks/registry
```

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `204` | No Content (successful deletion) |
| `400` | Bad Request (invalid input) |
| `404` | Not Found |
| `413` | Payload Too Large (media exceeds 25 MB) |
| `422` | Validation Error (Pydantic) |
| `429` | Too Many Requests (rate limited) |
| `500` | Internal Server Error |

### Rate Limiting

Requests exceeding 60/minute per IP receive `429` with:

```json
{"detail": "Rate limit exceeded: 60 per 1 minute"}
```

### Validation Errors

Pydantic validation errors return `422` with:

```json
{
  "detail": [
    {
      "loc": ["body", "entry_date"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Interactive Docs

When running in development mode, interactive API documentation is available at:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

> These are disabled in production (`APP_ENV=production`).
