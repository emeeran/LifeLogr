# Changelog

All notable changes to **LifeLogr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file ships inside the app — open **Settings → What's New** to read it
offline at any time.

---

## [Unreleased]

### Added
- **Backup integrity manifest + verify.** Every archive now carries
  `manifest.json` (format, app version, per-member size + sha256, totals), written
  as members are hashed — no second pass over the data. Restore verifies it
  **before** extracting or swapping, so a truncated download or a bit-rotted file
  can never replace good data; a failure names the offending member. Legacy
  archives without a manifest still restore, with a warning. New
  `POST /backup/verify` and a **Verify** button in Settings → Backup check an
  archive without restoring anything.
- **Fill missing titles** (Maintenance): preview how many untitled entries would gain
  a title from their first meaningful line, then apply. Never overwrites an existing
  title, and refreshes the sync fingerprint so a later Diarium pull does not read the
  backfill as a local edit.
- **Recovery kit** (Settings → Data → Security): wraps the encryption key
  under a passphrase or a generated 24-character recovery code and saves
  `lifelogr-recovery.json`. Import verifies the key against a stored
  credential and an encrypted attachment before installing it — a kit from a
  different installation is refused, and replacing an active key always asks
  for confirmation. Settings shows a warning while encryption is in use
  without a kit. Losing `SECRET_KEY` loses stored cloud credentials and all
  encrypted attachments — this is the way back.
- **"Encrypt attachments of encrypted items"** (Maintenance): migrates media
  that predates the encryption feature. Previews first (counts + bytes), is
  resumable, atomic per file, and never deletes the only copy — a failed file
  stays untouched and is named in the report. Also cleans plaintext
  thumbnails that predate the encrypted thumbnail cache.
- **Share exports omit attachments of encrypted entries** (HTML, markdown,
  Diarium, Day One): exporting a decrypted attachment alongside its
  passphrase-encrypted body would leak exactly the content that was hidden.
  The native archive (`/export/archive`, backups) still carries them **as
  ciphertext** so restore keeps working. HTML and PDF exports now also say so
  inline on the encrypted entry (matching the markdown frontmatter note).
  See `docs/SECURITY.md` for the full what-is/isn't-encrypted picture.
- **Manual note & notebook ordering in the Notes rail.** Drag a note to the top
  or bottom edge of another note in the same list — an insertion line appears and
  the drop reorders the list (remembered per list, pinned notes still first).
  Notebooks reorder the same way between siblings; the middle of a row still
  nests into it. Reordering is one batch call to the new
  `POST /notes/reorder` / `POST /notes/folders/reorder` endpoints. Lists that
  were never reordered keep the recent-first behaviour.
- **Preview media cap**: a preview renders at most 12 inline images/videos, with a
  "Show N more" control — the second half of the blank-screen memory fix.
- **New images insert at ≤ 480 px wide** (aspect preserved) instead of full bleed;
  the resize grip grows them again.
- **"Move to…" menu on notebook rows**, excluding the notebook and its descendants —
  the keyboard/pointer equivalent of the drag-and-drop move.
- **The voice recorder is reachable in focus mode** (floating button; the controls
  bar stays hidden).
- **Drag-and-drop in the Notes rail.** Drag a note onto a notebook to file it, or
  onto **Unfiled** to un-file it; drag a notebook onto another to nest it, or onto
  the **Notebooks** header to return it to the top level. The drop target is
  highlighted, and a move that would create a cycle (a notebook into itself or one
  of its descendants) is rejected with a toast — instead of the backend's silent
  no-op. Resolution logic lives in `composables/useNotesTreeDrag.ts` and is unit
  tested (15 cases).
- **Renderer error reporting + a view error boundary.** A crashing component used
  to unmount its subtree and leave an empty panel with no trace (the "screen goes
  blank" report). Views are now wrapped in `ErrorBoundary` (message, Reload, Copy
  details), and Vue/window/unhandled-rejection errors are logged via
  `POST /api/v1/system/client-errors` — message/stack/component/view only, query
  strings stripped, deduplicated and rate-limited. Entry text is never sent.
- **Notebook & note colour labels.** The `Note.color` / `NoteFolder.color` columns
  existed but nothing in the UI used them. Notebooks now show a colour stripe and
  notes a dot (a note inherits its notebook's colour), both set from a swatch picker
  in the notebook row and the note editor. Eight palette tones are contrast-checked
  against both themes, and the colour name is part of each row's accessible name.
- **Auto-title from the first line.** An empty, untouched title is filled from the
  body's first meaningful line on save (headings, list/quote markers, links, images
  and inline markdown stripped; 120 chars, word-boundary truncation). A typed or
  deliberately cleared title is never overwritten. `Auto:` chip applies the
  suggestion immediately; toggle under Settings → Appearance.
- **Visible resize grip for embedded media.** WebKit renders no affordance for the
  CSS `resize: both` corner, so pasted images looked un-resizable even though the
  mechanism worked. Both editors now show a corner grip + live size chip, with
  keyboard resizing (arrows, `Shift` = larger step).
- **Day One ZIP export — the push half of Diarium sync.** New
  `GET /entries/export/dayone-zip` (and a *Day One ZIP (Diarium push)* row in
  Settings → Export) writes `Journal.json` plus `photos/<md5>.<ext>`, the shape
  Diarium's **Migrate from other app → Day One** imports *with* attachments
  (it resolves each file by the md5 in its name). `scope=new` (default) exports
  only entries Diarium lacks — nothing that came from Diarium, and nothing on a
  day it already holds — while `scope=all` is a full one-way archive. Encrypted
  entries are skipped and counted in the ZIP's metadata.
- **Repeatable Diarium pulls (merge-mode import).** Imported `.diary` entries now
  keep the source's own identity (`DiaryEntryId` in `entries.external_id`) and a
  text fingerprint (`sync_hash`), so re-importing a newer backup reconciles with
  the rows already here instead of appending copies of them. Attachments are
  matched by content hash: a partially lost entry is repaired, an unchanged photo
  is not duplicated. Local edits win over a pull and are reported as a conflict
  (`conflicts` in the response). `POST /entries/import/file?mode=append` keeps
  the old always-insert behaviour. Run `make test` → `test_import_diarium_merge`.

### Changed
- **Attachments of encrypted items can now be encrypted at rest**
  (`ENCRYPT_MEDIA` rollout flag, default off). When enabled, uploads attached to
  an encrypted entry or note are stored as chunked AES-256-GCM blobs (1 MiB
  chunks, random nonce prefix, storage path bound as AAD — see
  `docs/design/media-encryption.md`), so a photo in a private entry is no
  longer a decodable file on disk or in backups. Serving decrypts on the fly:
  `/file` honours HTTP Range requests by decrypting only the chunks the range
  overlaps (video seeking stays cheap), `/thumb` keeps an **encrypted**
  thumbnail cache (`.webp.llm1`) and serves decrypted bytes, and OCR reads
  plaintext from memory only. A blob that fails authentication (wrong key,
  tampering, copied paths) returns **409** and is never deleted or
  overwritten. Existing plaintext media migrates via the upcoming Maintenance
  action.
- **Preview images load a ≤640 px thumbnail** (`/media/{id}/thumb`) unless the
  body encodes an explicit `?w=&h=` size, and render with `loading="lazy"` /
  `decoding="async"`. Full-resolution decodes of media-heavy entries were the
  main driver of WebKitWebProcess memory growth on the desktop build.
- **Closing the app no longer blocks the UI.** Teardown moved off the event loop
  onto a worker thread (hide window → bounded stop → exit), SIGTERM goes to the
  PID that owns the backend port instead of a `pkill -f` name match, and the
  backend's own teardown shares a 2 s deadline. If a backup/import/restore is in
  flight, the app shows a "Finishing backup…" dialog and waits for it (up to
  120 s, cancellable) instead of truncating the archive.
- **The voice-memo mic moved into the editor's bottom bar**, next to the read-aloud
  speaker, replacing the floating corner button. The recording pill (meter, timer,
  Stop) stays a popover above the bar.

### Fixed
- **Screen snip works on Wayland.** `xcap` needs `zwlr_screencopy_manager_v1`,
  which GNOME does not implement, so capture always failed with "Cannot find
  required wayland protocol". Capture now goes through
  `org.freedesktop.portal.Screenshot` (v2) on Wayland, falls back to the
  interactive portal selection and then `gnome-screenshot`, and only uses xcap on
  X11. The error toast names the path that actually failed.
- A `.diary` entry with only a heading and an empty body (Diarium anniversary /
  event entries) is imported instead of being dropped as empty noise.

---

## [0.12.0] — 2026-10-25

### Added
- **Media-aware export/import.** New native **Archive ZIP** export
  (`/entries/export/archive`) carries entries together with their media files
  (`lifelogr.json` + `media/`); importing it recreates the media rows and
  rewrites the body's `/api/v1/media/{id}/file` links to the new ids. The
  `.diary` export now embeds attachments as real Diarium Media rows (blob +
  name + order, Type mapped image/audio/document/video), and importing a real
  Diarium backup extracts those blobs into LifeLogr — photo-only entries (no
  text) are no longer dropped. The Markdown ZIP export lists each entry's
  media in its frontmatter, and re-importing the ZIP re-attaches the files
  with the same link rewriting.

### Fixed
- **Cloud-backup OAuth failed on any port other than 18765.** The loopback
  redirect URIs for Google Drive / Dropbox / OneDrive / Box were hardcoded to
  port 18765, but dev launches the backend on a free port — the consent
  screen sent the browser somewhere nothing listened. The redirect URI is now
  derived from the request host (loopback-gated, so a spoofed Host header
  can't redirect the authorization code off-machine) and the token exchange
  reuses the identical URI. Unchanged for the packaged desktop app.
- **Google Drive connect died with `redirect_uri_mismatch` on Web-type OAuth
  clients.** Desktop-type clients accept any loopback port; see the setup docs
  for creating the right client kind.
- **Saving cloud-backup settings showed "Internal server error" when
  `SECRET_KEY` was still the shipped default.** The deliberate
  credential-encryption refusal now surfaces as a 400 with the actual
  remediation ("Set a SECRET_KEY in .env") instead of an opaque 500.
- **Diarium compatibility, verified against the shipped app.** The `.diary`
  export now builds the exact six-table schema extracted from the Diarium
  3.3.12.0 binary (previously `Tags.Type` — a NOT NULL column — was missing,
  and unrated latitudes were written as NULL into NOT NULL columns), so the
  file passes Diarium's backup restore. Added a **Daylio-format CSV export**,
  Diarium's documented migration import (Settings → Database → Migrate from
  other app → CSV; `great` maps to Daylio's `rad`). The `.diary` importer now
  understands real Diarium backups (imports tag + person tags, skips tracker
  tags) and the JSON importer accepts Diarium's capitalized, tick-keyed entry
  shape. The JSON-export docstring no longer claims Diarium can import it.

---

## [0.11.0] — 2026-10-18

A security, correctness, and durability pass across the whole codebase
(~110 findings from a four-track audit; see `docs/audit-2026-10-18.md`).

### Security
- **HTML exports are no longer an XSS vector.** Exported HTML escapes raw
  markup and user fields, and downloads as an attachment with a sandboxing
  CSP — imported journal content can no longer execute script when the
  export is opened.
- **The desktop webview can no longer run arbitrary programs or read
  arbitrary files.** Tauri shell/fs capabilities are scoped; permission
  requests (camera, geolocation, …) are denied by default — only microphone
  capture is granted, and WebRTC peer connections are off.
- **The local API validates the `Host` header** (defeats DNS-rebinding
  reads) and supports an optional `API_TOKEN` for deployments that want
  bearer auth on every `/api` call.
- **Cloud AI consent.** Pointing Ollama at a non-loopback host now requires
  an explicit confirmation, since that URL receives journal text.
- **Read-aloud is now in the egress report.** The Privacy tab no longer claims
  it lists every off-device surface while silently omitting Edge TTS (which
  sends the text being read to Microsoft).
- OAuth sign-in flows (Drive/OneDrive/Dropbox/Box) use **PKCE**, and
  consent-denied redirects show a proper error page.
- "Encrypt selection" now uses the **salted scrypt v2** key derivation
  (legacy blobs still decrypt), and encrypting an entry deletes its
  semantic embedding so locked content stops being similarity-searchable.
- Credentials are never encrypted under the shipped default `SECRET_KEY` —
  that configuration now fails loudly instead of warning.

### Fixed
- **Multi-tag list filters actually filter.** Tag-id lists now reach the
  entries/notes list endpoints in the comma-separated form the backend parses
  (previously they were sent as repeated params, which the backend silently
  reduced to one tag), the global search store's mood filter is no longer
  dropped before it reaches the API, and selecting a very long passage before
  running an AI tool shows a clear message instead of a raw 422.
- **Restores can no longer resurrect pre-restore data** via stale SQLite
  WAL sidecars; backups that bundled a WAL now restore with it.
- **Exports no longer lose entries**: markdown filenames include the entry
  id so same-day entries don't overwrite each other, and tag filters no
  longer duplicate entries (or inflate totals) when an entry matches two
  selected tags.
- **Imports keep their tags and GPS coordinates**, stream to disk with a
  size cap instead of loading whole archives into memory, and report why
  individual records were skipped.
- **Cloud backup uploads/restore were broken at runtime** (blocking file
  handles handed to the async HTTP client) — now streamed, with Drive
  using resumable uploads for large archives and old cloud backups pruned
  to a configurable retention.
- A failed cloud restore no longer reports "Restore failed" after
  succeeding (and 409 is no longer the answer to every failure class).
- Failed note saves are no longer silent — store errors surface as toasts.
- Unsaved note edits now prompt before navigation discards them.
- Voice-memo playback works in the packaged desktop app again (media URLs
  were relative to the wrong origin).
- The sidebar view and the URL can no longer disagree (Back/Forward,
  search/Timeline jumps).
- Deleted entries are no longer read aloud, and encrypted entries no
  longer read base64 ciphertext aloud.
- Docker deploys actually boot: the database volume mount, the missing
  media/data env, and a nonexistent dependency extra are fixed; images get
  a healthcheck and exclude dev state.
- Search stays responsive when Ollama hangs (short embed timeouts,
  single-flight); a model swap no longer 500s every semantic search; the
  search index self-heals content drift, and its triggers are no longer
  rebuilt on every app start.
- Journal exports, media compression, encryption, and storage relocation
  no longer freeze the whole app while they run (moved off the UI/API
  thread); video playback now supports seeking.

### Removed
- **The dedication splash no longer plays music.** The memorial tab and
  startup splash are unchanged — only the audio (and its bundled track) is
  gone, so LifeLogr no longer spawns a system audio player or ships an MP3.

### Changed
- Semantic/hybrid search reports accurate totals; semantic-only search
  skips notes/reminders that have no embeddings.
- Missing foreign-key indexes added (media, recordings, note media,
  prompts, backups) — faster pages as libraries grow.

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
