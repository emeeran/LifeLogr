# Changelog

All notable changes to **LifeLogr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file ships inside the app — open **Settings → What's New** to read it
offline at any time.

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
