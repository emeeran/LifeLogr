# Changelog

All notable changes to **LifeLogr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file ships inside the app — open **Settings → What's New** to read it
offline at any time.

---

## [0.10.1] — 2026-08-07

### Changed
- **Calendar: double-click to open.** Single-clicking a date now just selects
  (highlights) it; double-click opens the journal for that date — one entry
  opens it, several show the picker, and an empty date opens a new-entry editor.
  (Previously a single click opened immediately.)

---

## [0.10.0] — 2026-08-06

### Added
- **Auto-OCR toggle.** A new **Settings → Appearance → "Auto-OCR images"** switch
  controls whether images you add (attach, paste, drag-drop, or screen-snip) are
  OCR'd automatically. **On** (default) extracts the text and inserts it alongside
  the image, as before; **Off** embeds images as-is with no OCR — useful when you
  want to keep an image as a picture rather than text. The manual "Extract text"
  action on any image still works in either state.

---

## [0.9.0] — 2026-08-06

### Added
- **OCR language selection.** Image text extraction (Tesseract) now runs in the
  language you pick under **Settings → Appearance → "OCR language"**. English
  (`eng`) and Tamil (`tam`) ship with their data packs; the code is whitelisted,
  so an unknown/garbage value is rejected cleanly instead of being passed to the
  binary.

### Fixed
- **OCR error reporting.** When tesseract runs but a language's trained data
  isn't installed, you now get a clear, language-specific message naming the pack
  to install (e.g. `tesseract-ocr-tam`) — not a generic failure.

---

## [0.8.0] — 2026-08-04

A release centered on **tagging that stays out of your way** and **database
durability**.

### Added
- **Inline hashtag tagging.** Tags now live in your text: type `#hashtag` anywhere in
  an entry or note and it becomes a tag, with **autocomplete** as you type `#` in both
  editors. Tags are derived server-side from the `#tokens` in the body
  (`services/hashtag.py`) and synced on save — so adding, renaming, or removing a
  `#tag` in the text is all you ever do (editor-sent tag ids are ignored on save).
- **Nested note folders.** `NoteFolder` now supports sub-folders (with an acyclic
  re-parenting guard) for deeper organization in the Notes tree.
- **Boot-time DB snapshot + integrity auto-recovery.** Before migrations run, the app
  takes a rotating `lifelogr.db.boot-bak-*` snapshot; if `PRAGMA integrity_check` fails
  at boot, the newest good snapshot is restored automatically and the corrupt file is
  quarantined — your journal survives a botched migration or a crash mid-write.

### Changed
- Diagnostics panel restyled with proper light/dark color tokens.

### Fixed
- **Version parity:** `APP_VERSION` in `config.py` now tracks the other three version
  sources (pyproject / Cargo / tauri.conf), so the in-app About version can't drift.

---

## [0.7.1] — 2026-07-27

A major release focused on **AI choice, privacy transparency, encryption strength,
and reliability** — backed by a large test-coverage and CI expansion under the hood.

### Added
- **Multi-provider AI.** Beyond local Ollama, connect any OpenAI-compatible cloud
  provider — **OpenAI, Groq, OpenRouter, Kimi (Moonshot), Google Gemini**, or a
  **Custom** endpoint — and choose which is active. **Ollama stays the automatic
  fallback** if the active provider is unreachable. API keys are AES-GCM encrypted at
  rest and never returned by the API. *(Settings → AI)*
- **Privacy tab + data-egress report.** A new *Settings → Privacy* tab shows,
  surface-by-surface, exactly what leaves your device (AI tools, embeddings, cloud
  backup, web-clip, OCR) and flags when a cloud AI provider is active. Powered by
  `GET /system/egress-report`.
- **Stronger entry/note encryption.** New passphrase-encrypted items now derive their
  key with a **memory-hard scrypt KDF** (AES-256-GCM, per-item salt), making brute-force
  of short passphrases far more expensive. Legacy items still decrypt.
- **Cloud backup providers (OAuth).** Connect **Google Drive, OneDrive, Dropbox, or
  Box** via loopback OAuth sign-in (callback on `127.0.0.1:18765`), or **WebDAV /
  Synology NAS** with manual credentials. Tokens are encrypted and auto-refreshed.
- **Diarium interop.** Import from and export to Diarium — including the native `.diary`
  SQLite format, plus JSON and Markdown-ZIP archives.
- **Startup integrity battery + self-heal.** On boot the app runs a broader integrity
  check (DB structure, FTS, encryption key) and self-heals where it can; a Diagnostics
  panel exposes maintenance actions.
- **Rebuild search index** endpoint + Diagnostics button, with idempotent FTS
  repopulation.
- **Tag typeahead picker** in the entry editor.
- **Notes import/export** in Markdown ZIP, JSON, and HTML.

### Changed
- **Settings redesigned** from 8 tabs down to a cleaner set (Appearance, AI, Data,
  Backup, Privacy, Dedication, About).
- **Performance:** lazy-loaded `fpdf2` (−~450 ms startup, −~32 MB RSS), split vendor
  chunks (entry bundle 209 KB → 134 KB), virtualized list views, body-snippet
  projection on list/search queries, and SQLite tuning (4 MB cache, capped WAL
  autocheckpoint, **incremental `auto_vacuum`** with a daily vacuum maintenance job).
- Background sync/AI pollers now **pause when the window is hidden**.
- Desktop sidecar now **loads `.secret_key`** and uses a larger SQLite pool (fixes
  desktop-only decryption failures).
- Greyer theme background with enhanced text visibility.

### Fixed
- **Backup-restore path-traversal** hardened on both the restore and import paths.
- **Full-text search works in the packaged desktop app** — the `pysqlite3` swap resolves
  the FTS5 qualified-column bug that previously forced skipping FTS in frozen builds.
- FTS triggers made **restore- and encrypt-safe** (ciphertext is never indexed; undelete
  re-indexes plaintext).
- Web-clip **SSRF hardening**: internal/loopback IPs blocked, DNS-rebinding guard,
  re-validated on every redirect hop.
- SQLite reliability: no re-`SET auto_vacuum` per pooled connection; cursor/`fetchone()`
  fix for `pysqlite3`; reduced write-lock contention.
- Desktop NoteEditor `Ctrl+V` text paste.

### Security
- Memory-hard scrypt KDF for passphrase encryption (see Added).
- Cloud-AI egress made explicit and auditable (Privacy tab + egress report).
- Credential encryption upgraded to HKDF (v2); legacy v1 tokens auto-migrate on write.
- SSRF guards on web-clip; tar extraction uses PEP 706 `filter="data"`.

### Removed
- **Scoped to journaling + notes.** The app is now focused on the journal and notes
  experience. The **Email, Contacts, Dashboard, and Schedule/Tasks (Google
  Calendar/Tasks sync)** surfaces have been removed. *(Reminders, Tags, Media,
  search, and cloud backup remain.)*

### Quality & CI
- Major **test-coverage expansion**: backup cloud-restore orchestration, Dropbox/Box
  token-refresh contracts, AI provider connection/model-list error paths, search-index
  rebuild idempotency, and the Diarium `.diary` export endpoint.
- New **CI gates**: a coverage floor, **version-parity** check across the four version
  sources, **cargo-check** for the Tauri shell, **vitest** wired into CI, cached Rust
  builds, and **macOS-Intel** release builds.
- Code-health refactors: shared OAuth HTTP-client base, extracted `cron_utils`
  (cron→occurrence math), `importers/` and `export_service` packages, a shared OAuth
  callback base, and FTS-query escaping.

---

## [0.7.0] — 2026-07-17

### Added
- **Screen-snippet + web-clip with OCR (Notes).** Snip a region of your screen
  (`Ctrl+Shift+S`, desktop) or clip a web page, embed it as a picture, and **OCR the
  text** straight into the note — instantly searchable.
- **Manual save for Notes** (autosave off); opening Notes creates a fresh blank note,
  ready to write or clip.

### Fixed
- Web-clip **SSRF** redirect and DNS-rebinding protection.

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
