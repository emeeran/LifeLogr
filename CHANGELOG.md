# Changelog

All notable changes to **LifeLogr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file ships inside the app — open **Settings → What's New** to read it
offline at any time.

---

## [Unreleased]

Staged on the `feature/perf-and-debloat` and `cleanup/pipeline-*` branches; will
land in the next release.

### Changed
- **Performance pass.** Backend query consolidation: the tags tree went from
  `1+2N` queries to 2; the analytics overview/media-stats endpoints collapsed to
  scalar subqueries; the planner agenda now filters non-recurring events in the
  database instead of loading the table. On the frontend, code-splitting the
  on-demand editor panels shrank the entry route's initial chunk from ~211 kB to
  ~35 kB (near-free in the Tauri shell, where assets load from local disk).
- **Codebase cleanup.** Removed dead response types, orphan files, and duplicated
  helpers; unified the `errMsg()` helper, the Google Calendar/Tasks sync helpers
  (`google_sync_utils`), and the cloud-provider OAuth result page. No
  user-visible behaviour change — 389 backend tests still pass.

### Added
- **Production-readiness audit.** A six-dimension audit and an independent blind
  review now document exactly what is and isn't shippable, with `file:line`
  references — see [`AUDIT.md`](AUDIT.md) and `.pipeline/blind-review.md`.

### Fixed
- Web-clip SSRF hardening extended to every redirect hop, blocking DNS-rebinding
  attempts to internal hosts.

---

## [0.7.0] — 2026-07-17

This release consolidates everything new since the last documented **[0.2.1]**
(the intermediate 0.3–0.6 versions were not separately tagged in git).

### Added
- **Notes mode** — a full standalone-notes workspace alongside the date-bound
  journal: notebooks, tabbed pages, markdown, tags, and per-note encryption.
  Notes have their own FTS5 search and appear in the global search palette.
- **Clipping & OCR.** Snip a screen region (`Ctrl+Shift+S`, desktop) or clip a
  web page, embed it as a picture, and **OCR the text** (Tesseract) straight into
  the note body — instantly searchable.
- **Email (IMAP/SMTP).** A built-in mail client: multiple accounts, auto-detected
  folders, threaded reading, compose & send with attachments, and spam blocking.
- **Google two-way sync.** Calendar and Tasks sync (plus Contacts via the People
  API) with provenance tracking; `POST /sync/all`. Mail stays on IMAP.
- **Planner (Tasks)** — task lists with subtasks, completion, and reordering;
  optionally syncs with Google Tasks.
- **Contacts address book** — names, emails, phones, photos, groups, favorites;
  vCard (`.vcf`) import/export; linkable to email messages.
- **Read aloud (TTS)** — Microsoft Edge TTS with voice / rate / volume / pitch
  controls and a disk cache; seekable streaming playback.
- **Analytics dashboard** — streaks, word counts, mood distribution, writing
  habits, a GitHub-style heatmap, sentiment timeline, tag stats, and media stats.
- **Hybrid search** — full-text (FTS5, BM25) **plus** semantic vector search
  (`nomic-embed-text`), fused via Reciprocal Rank Fusion across entries, notes,
  and tasks.
- **Two ways to run** — a native **desktop app** (Tauri) and a lighter **web app**
  (browser-served `.deb`). Only the desktop build supports screen-snipping.
- **Scheduled, DB-backed local backup** with boot catch-up, plus cloud backup via
  **Google Drive / OneDrive / Dropbox / Box** (OAuth, loopback callback on
  `127.0.0.1:18765`); credentials stored encrypted.

### Changed
- **Encryption hardened** — per-entry random salts (legacy single-salt entries
  still decrypt); encrypted entries' ciphertext is excluded from the FTS5 search
  index and is never sent to the LLM for enrichment.
- Rate limiting is now scoped to production deployments only — the desktop app no
  longer self-throttles its own background enrichment.
- Cloud-provider OAuth client IDs/secrets can be stored per-config (encrypted)
  and override the built-in defaults.

### Fixed
- Backup-restore symlink/hardlink traversal — tar extraction now uses
  `filter="data"` (PEP 706), neutralising escapes on both restore and import.
- Full-text search works in the packaged desktop app — FTS5 setup is no longer
  skipped under PyInstaller.
- Production `SECRET_KEY` validation fires for server deployments even when
  `DATA_DIR` is unset.
- FTS triggers made restore-safe (guarded delete+insert; a restore trigger
  re-indexes entries on undelete).

### Removed
- **Speech-to-text transcription (Whisper).** Recordings are now stored as audio
  attachments only; the `faster-whisper` dependency and `WHISPER_*` settings were
  dropped.

---

## [0.2.1] — 2026-06-24

### Added
- **Reminders now fire automatically.** Per-reminder scheduling via APScheduler,
  reconciled with the database on startup and after every change, plus an
  offline catch-up sweep for reminders whose time passed while the app was down.
- **Entry restore.** Soft-deleted entries can be restored via
  `POST /entries/{id}/restore`; the FTS search index is re-populated correctly.
- **Structured health check.** `/health` now reports `database`, `fts`,
  `scheduler`, and `ollama` status independently.
- **Credential migration.** Backup credentials auto-upgrade from the legacy v1
  token format to v2 (HKDF) on write; new maintenance endpoint
  `POST /backup/config/migrate-credentials`.
- **"What's New" tab** and **"Check for updates"** affordance in Settings.
- `make bump V=x.y.z` target to keep all four version locations in sync.

### Changed
- **About UI redesigned:** hero card with logo, version badge, feature
  highlights, and a prominent full-width dedication memorial.
- About tab version is now injected at **build time** (`VITE_APP_VERSION`),
  so it always matches the installed `.deb` exactly.
- GitHub links now point to `github.com/emeeran/LifeLogr`.
- Rate limiting is now scoped to production deployments only (desktop no longer
  self-throttles its own background enrichment).
- Request-logging middleware skips noisy `/health` / static paths.

### Fixed
- **Backup restore symlink-traversal vulnerability.** Tar extraction now uses
  `filter="data"` (PEP 706), neutralising symlink/hardlink escapes on both the
  restore and import paths.
- **Full-text search works again in the packaged desktop app** — FTS5 setup no
  longer skipped in PyInstaller builds (the `pysqlite3` swap resolves the
  qualified-column bug that motivated the skip).
- **Production `SECRET_KEY` validation** now correctly fires for server
  deployments even when `DATA_DIR` is unset.
- FTS triggers made restore-safe: the update trigger is a guarded delete+insert,
  and a new restore trigger re-indexes entries on undelete.

### Removed
- Dead Alembic scaffolding (7 migrations + env) that drifted from the inline
  migration system. `_migrate_schema` is now the single canonical path.
- 33 MB compiled sidecar binary committed to git history (now gitignored; built
  fresh by CI / `make build-sidecar`).

---

## [0.2.0] — 2026-05-27

### Added
- **AI tool registry** — the editor's AI tools (rewrite, summarise, grammar,
  tag suggestions, reflection prompts, writer's-block helper, and more) are
  defined once in `aiToolRegistry.ts` and served by a single generic
  `POST /ai/tool/{tool_id}` endpoint.
- Unified AI drawer, right-click context menu, and `useAiTools` composable all
  iterate the registry — no per-tool boilerplate.

### Changed
- Rebranded as **LifeLogr**.

---

## [0.1.x] — 2026-05

### Added
- Privacy-first, offline-first journaling with markdown support.
- Media attachments, voice recording with local Whisper transcription, and
  Tesseract OCR.
- Local AI-assisted grammar checking, mood insights, and semantic vector search
  via Ollama.
- End-to-end encrypted cloud sync (Google Drive, WebDAV, Mega).
- Automated backups with retention, calendar/timeline/map views, and tags.
